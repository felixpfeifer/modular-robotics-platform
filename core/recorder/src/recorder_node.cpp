#include <rclcpp/rclcpp.hpp>
#include <rclcpp_action/rclcpp_action.hpp>
#include <rcutils/sha256.h>
#include <rosbag2_cpp/writer.hpp>
#include <rosbag2_cpp/reader.hpp>
#include <rosbag2_storage/storage_options.hpp>
#include <sensor_msgs/msg/compressed_image.hpp>
#include <sensor_msgs/msg/joint_state.hpp>
#include <std_msgs/msg/string.hpp>

#include <platform_control_interfaces/msg/command_rejection.hpp>
#include <platform_control_interfaces/msg/joint_intent.hpp>
#include <platform_control_interfaces/msg/safety_event.hpp>
#include <platform_episode_interfaces/action/record_episode.hpp>
#include <platform_episode_interfaces/action/validate_episode.hpp>
#include <platform_episode_interfaces/msg/episode_event.hpp>
#include <platform_episode_interfaces/msg/episode_metadata.hpp>
#include <platform_episode_interfaces/msg/episode_state.hpp>
#include <platform_episode_interfaces/srv/mark_episode.hpp>

#include <nlohmann/json.hpp>

#include <array>
#include <algorithm>
#include <atomic>
#include <chrono>
#include <cmath>
#include <condition_variable>
#include <deque>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <memory>
#include <mutex>
#include <random>
#include <cctype>
#include <sstream>
#include <string>
#include <thread>
#include <utility>
#include <vector>

#include "episode_recorder/episode_manager.hpp"
#include "episode_recorder/keyboard_handler.hpp"

namespace fs = std::filesystem;
using namespace std::chrono_literals;

namespace {

constexpr std::size_t kWriterQueueCapacity = 256ULL * 1024ULL * 1024ULL;

template<typename MessageT>
std::shared_ptr<rosbag2_storage::SerializedBagMessage> serialize_message(
    const MessageT& message, const std::string& topic, int64_t receive_ns, int64_t source_ns) {
    rclcpp::Serialization<MessageT> serializer;
    rclcpp::SerializedMessage serialized;
    serializer.serialize_message(&message, &serialized);
    auto bag_message = std::make_shared<rosbag2_storage::SerializedBagMessage>();
    bag_message->topic_name = topic;
    bag_message->recv_timestamp = receive_ns;
    bag_message->send_timestamp = source_ns > 0 ? source_ns : receive_ns;
    bag_message->serialized_data = std::make_shared<rcutils_uint8_array_t>(
        serialized.release_rcl_serialized_message());
    return bag_message;
}

template<typename TimeT>
int64_t to_nanoseconds(const TimeT& time) {
    return static_cast<int64_t>(time.sec) * 1000000000LL + time.nanosec;
}

std::string uuid_to_string(const unique_identifier_msgs::msg::UUID& value) {
    std::ostringstream out;
    out << std::hex << std::setfill('0');
    for (std::size_t i = 0; i < value.uuid.size(); ++i) {
        out << std::setw(2) << static_cast<int>(value.uuid[i]);
        if (i == 3 || i == 5 || i == 7 || i == 9) out << '-';
    }
    return out.str();
}

unique_identifier_msgs::msg::UUID random_uuid() {
    unique_identifier_msgs::msg::UUID value;
    std::random_device random;
    for (auto& byte : value.uuid) byte = static_cast<uint8_t>(random());
    value.uuid[6] = static_cast<uint8_t>((value.uuid[6] & 0x0fU) | 0x40U);
    value.uuid[8] = static_cast<uint8_t>((value.uuid[8] & 0x3fU) | 0x80U);
    return value;
}

std::string sha256_file(const fs::path& path) {
    std::ifstream input(path, std::ios::binary);
    if (!input) throw std::runtime_error("cannot hash " + path.string());
    rcutils_sha256_ctx_t context;
    rcutils_sha256_init(&context);
    std::array<char, 1024 * 1024> buffer{};
    while (input) {
        input.read(buffer.data(), static_cast<std::streamsize>(buffer.size()));
        const auto count = input.gcount();
        if (count > 0) {
            rcutils_sha256_update(
                &context, reinterpret_cast<const uint8_t*>(buffer.data()),
                static_cast<std::size_t>(count));
        }
    }
    std::array<uint8_t, RCUTILS_SHA256_BLOCK_SIZE> digest{};
    rcutils_sha256_final(&context, digest.data());
    std::ostringstream out;
    out << "sha256:" << std::hex << std::setfill('0');
    for (const auto byte : digest) out << std::setw(2) << static_cast<int>(byte);
    return out.str();
}

bool is_sha256(const std::string& value) {
    return value.size() == 71 && value.rfind("sha256:", 0) == 0 &&
        value.substr(7) != std::string(64, '0') &&
        std::all_of(value.begin() + 7, value.end(), [](unsigned char character) {
            return std::isxdigit(character) != 0;
        });
}

rosbag2_storage::TopicMetadata topic(const std::string& name, const std::string& type_name) {
    rosbag2_storage::TopicMetadata metadata;
    metadata.name = name;
    metadata.type = type_name;
    metadata.serialization_format = "cdr";
    return metadata;
}

}  // namespace

class RecorderNode final : public rclcpp::Node {
public:
    using RecordEpisode = platform_episode_interfaces::action::RecordEpisode;
    using GoalHandleRecord = rclcpp_action::ServerGoalHandle<RecordEpisode>;
    using ValidateEpisode = platform_episode_interfaces::action::ValidateEpisode;

    RecorderNode() : Node("episode_recorder") {
        declare_parameter("dataset_dir", "/data/datasets/teleop");
        declare_parameter("recording_profile_id", "");
        declare_parameter("recording_profile_hash", "");
        declare_parameter("task_id", "default_demo");
        declare_parameter("workcell_id", "local_so101");
        declare_parameter("configuration_hash", "sha256:0000000000000000000000000000000000000000000000000000000000000000");
        declare_parameter("calibration_id", "so101-default");
        declare_parameter("calibration_hash", "sha256:0000000000000000000000000000000000000000000000000000000000000000");
        declare_parameter("source_revision", "development");
        declare_parameter("camera_topics", std::vector<std::string>{});
        declare_parameter("camera_expected_fps", std::vector<double>{});
        declare_parameter("camera_fps_tolerances", std::vector<double>{});
        declare_parameter("joint_state_topic", "/joint_states");
        declare_parameter("action_topic", "/platform/control/joint_intent");
        declare_parameter("mcap_config", "");
        declare_parameter("recording_profiles", "");
        declare_parameter("task_catalog", "");
        declare_parameter("preflight_min_free_gib", 10.0);
        declare_parameter("runtime_reserve_gib", 5.0);

        dataset_dir_ = get_parameter("dataset_dir").as_string();
        camera_topics_ = get_parameter("camera_topics").as_string_array();
        camera_expected_fps_ = get_parameter("camera_expected_fps").as_double_array();
        camera_fps_tolerances_ = get_parameter("camera_fps_tolerances").as_double_array();
        if (camera_topics_.empty() || camera_topics_.size() != camera_expected_fps_.size() ||
            camera_topics_.size() != camera_fps_tolerances_.size()) {
            throw std::invalid_argument("camera topic/rate/tolerance arrays must be non-empty and equal length");
        }
        joint_state_topic_ = get_parameter("joint_state_topic").as_string();
        action_topic_ = get_parameter("action_topic").as_string();
        mcap_config_ = get_parameter("mcap_config").as_string();
        recording_profiles_ = get_parameter("recording_profiles").as_string();
        task_catalog_ = get_parameter("task_catalog").as_string();
        manager_ = std::make_unique<episode_recorder::EpisodeManager>(dataset_dir_);

        last_camera_ns_.resize(camera_topics_.size());
        image_receipts_.resize(camera_topics_.size());
        for (std::size_t index = 0; index < camera_topics_.size(); ++index) {
            last_camera_ns_[index] = std::make_shared<std::atomic<int64_t>>(0);
            const auto camera_topic = camera_topics_[index];
            image_subscriptions_.push_back(create_subscription<sensor_msgs::msg::CompressedImage>(
                camera_topic, rclcpp::QoS(100).best_effort(),
                [this, index, camera_topic](sensor_msgs::msg::CompressedImage::ConstSharedPtr msg) {
                    note_camera_sample(index);
                    if (recording_) enqueue(serialize_message(
                        *msg, camera_topic, now().nanoseconds(), to_nanoseconds(msg->header.stamp)));
                }));
        }
        state_sub_ = create_subscription<sensor_msgs::msg::JointState>(
            joint_state_topic_, rclcpp::QoS(100).reliable(),
            [this](sensor_msgs::msg::JointState::ConstSharedPtr msg) {
                last_state_ns_ = now().nanoseconds();
                if (recording_) enqueue(serialize_message(
                    *msg, joint_state_topic_, now().nanoseconds(), to_nanoseconds(msg->header.stamp)));
            });
        action_sub_ = create_subscription<platform_control_interfaces::msg::JointIntent>(
            action_topic_, rclcpp::QoS(100).reliable(),
            [this](platform_control_interfaces::msg::JointIntent::ConstSharedPtr msg) {
                const auto clock_ns = now().nanoseconds();
                auto receipt_ns = clock_ns;
                last_action_ns_ = clock_ns;
                {
                    std::lock_guard<std::mutex> lock(samples_mutex_);
                    // Multiple DDS callbacks can be drained during the same
                    // simulation-clock tick. Preserve their real callback
                    // ordering with a one-nanosecond tie break.
                    if (!recent_actions_.empty() &&
                        receipt_ns <= recent_actions_.back().second) {
                        receipt_ns = recent_actions_.back().second + 1;
                    }
                    recent_actions_.emplace_back(msg, receipt_ns);
                    // Camera encoding and DDS delivery can make the first frame
                    // recorded after start carry a slightly earlier source stamp.
                    // Retain one second of commands so the episode has a truthful
                    // causal action pre-roll for that initial observation.
                    while (!recent_actions_.empty() &&
                           recent_actions_.front().second < clock_ns - 1000000000LL) {
                        recent_actions_.pop_front();
                    }
                }
                if (recording_) enqueue(serialize_message(
                    *msg, action_topic_, receipt_ns, to_nanoseconds(msg->issued_at)));
            });
        safety_sub_ = create_subscription<platform_control_interfaces::msg::SafetyEvent>(
            "/platform/control/safety_events", rclcpp::QoS(50).reliable(),
            [this](platform_control_interfaces::msg::SafetyEvent::ConstSharedPtr msg) {
                if (recording_) enqueue(serialize_message(
                    *msg, "/platform/control/safety_events", now().nanoseconds(),
                    to_nanoseconds(msg->header.stamp)));
            });
        rejection_sub_ = create_subscription<platform_control_interfaces::msg::CommandRejection>(
            "/platform/control/command_rejections", rclcpp::QoS(50).reliable(),
            [this](platform_control_interfaces::msg::CommandRejection::ConstSharedPtr msg) {
                if (recording_) enqueue(serialize_message(
                    *msg, "/platform/control/command_rejections", now().nanoseconds(),
                    to_nanoseconds(msg->header.stamp)));
            });

        state_pub_ = create_publisher<platform_episode_interfaces::msg::EpisodeState>(
            "/platform/episode/state", rclcpp::QoS(10).transient_local().reliable());
        event_pub_ = create_publisher<platform_episode_interfaces::msg::EpisodeEvent>(
            "/platform/episode/events", rclcpp::QoS(50).reliable());
        metrics_pub_ = create_publisher<std_msgs::msg::String>(
            "/platform/episode/metrics", rclcpp::QoS(10).reliable());
        mark_service_ = create_service<platform_episode_interfaces::srv::MarkEpisode>(
            "/platform/episode/mark",
            [this](const std::shared_ptr<platform_episode_interfaces::srv::MarkEpisode::Request> request,
                   std::shared_ptr<platform_episode_interfaces::srv::MarkEpisode::Response> response) {
                handle_mark(*request, *response);
            });
        record_server_ = rclcpp_action::create_server<RecordEpisode>(
            this, "/platform/episode/record",
            [this](const rclcpp_action::GoalUUID&, std::shared_ptr<const RecordEpisode::Goal> goal) {
                return on_goal(*goal);
            },
            [this](const std::shared_ptr<GoalHandleRecord>) {
                if (!recording_ || terminal_requested_ || cancel_requested_) {
                    return rclcpp_action::CancelResponse::REJECT;
                }
                cancel_requested_ = true;
                finish_timer_->reset();
                return rclcpp_action::CancelResponse::ACCEPT;
            },
            [this](const std::shared_ptr<GoalHandleRecord> handle) { start_recording(handle); });
        validator_client_ = rclcpp_action::create_client<ValidateEpisode>(
            this, "/platform/episode/validate");
        record_client_ = rclcpp_action::create_client<RecordEpisode>(
            this, "/platform/episode/record");

        finish_timer_ = create_wall_timer(1ms, [this]() {
            finish_timer_->cancel();
            finish_requested_recording();
        }, nullptr, false);
        keyboard_ = std::make_unique<episode_recorder::KeyboardHandler>(
            [this](episode_recorder::KeyCommand command) { on_key(command); });
        keyboard_->start();
        monitor_timer_ = create_wall_timer(1s, [this]() { monitor(); });

        publish_state(platform_episode_interfaces::msg::EpisodeState::STATE_PENDING, "ready");
        RCLCPP_INFO(get_logger(), "MCAP recorder ready: Space=start, y=success, n=failure, a=annotation, q=quit");
    }

    ~RecorderNode() override {
        keyboard_->stop();
        if (recording_) finish_recording(false, true, "recorder shutdown");
    }

private:
    struct QueuedMessage {
        std::shared_ptr<rosbag2_storage::SerializedBagMessage> message;
        std::size_t bytes;
    };

    void note_camera_sample(std::size_t index) {
        const auto receipt = now().nanoseconds();
        *last_camera_ns_[index] = receipt;
        std::lock_guard<std::mutex> lock(samples_mutex_);
        auto& samples = image_receipts_[index];
        samples.push_back(receipt);
        while (!samples.empty() && receipt - samples.front() > 2000000000LL) samples.pop_front();
    }

    bool enough_disk(double gib) const {
        const auto space = fs::space(dataset_dir_);
        return static_cast<double>(space.available) >= gib * 1024.0 * 1024.0 * 1024.0;
    }

    rclcpp_action::GoalResponse on_goal(const RecordEpisode::Goal& goal) {
        RCLCPP_INFO(get_logger(), "received episode recording goal");
        if (recording_ || finishing_) return rclcpp_action::GoalResponse::REJECT;
        const auto id = uuid_to_string(goal.metadata.episode_id);
        const auto configured_profile = get_parameter("recording_profile_id").as_string();
        const auto configured_task = get_parameter("task_id").as_string();
        const auto configured_hash = get_parameter("configuration_hash").as_string();
        const auto configured_calibration_id = get_parameter("calibration_id").as_string();
        const auto configured_calibration_hash = get_parameter("calibration_hash").as_string();
        const bool producer_provenance_complete = std::all_of(
            goal.metadata.producers.begin(), goal.metadata.producers.end(),
            [&configured_hash](const auto& producer) {
                return !producer.component.component_id.empty() &&
                    !producer.component.semantic_version.empty() &&
                    !producer.component.source_revision.empty() &&
                    !producer.component.build_id.empty() &&
                    producer.configuration.content_hash == configured_hash &&
                    (producer.calibration_id.empty() || is_sha256(producer.calibration_hash));
            });
        if (id == "00000000-0000-0000-0000-000000000000" ||
            goal.metadata.task_id != configured_task || goal.metadata.recording_profile_id.empty() ||
            goal.metadata.recording_profile_id != configured_profile ||
            goal.metadata.configuration.content_hash != configured_hash || !is_sha256(configured_hash) ||
            !is_sha256(get_parameter("recording_profile_hash").as_string()) || goal.metadata.producers.empty() ||
            std::find(goal.metadata.calibration_ids.begin(), goal.metadata.calibration_ids.end(),
                configured_calibration_id) == goal.metadata.calibration_ids.end() ||
            !is_sha256(configured_calibration_hash) || recording_profiles_.empty() || task_catalog_.empty() ||
            !fs::is_regular_file(recording_profiles_) || !fs::is_regular_file(task_catalog_) ||
            !producer_provenance_complete) {
            RCLCPP_ERROR(get_logger(), "recording goal lacks required identity/provenance");
            return rclcpp_action::GoalResponse::REJECT;
        }
        const auto current = now().nanoseconds();
        const bool camera_stale = std::any_of(
            last_camera_ns_.begin(), last_camera_ns_.end(),
            [current](const auto& stamp) { return current - stamp->load() > 2000000000LL; });
        if (camera_stale || current - last_state_ns_.load() > 2000000000LL ||
            current - last_action_ns_.load() > 2000000000LL) {
            RCLCPP_ERROR(get_logger(), "preflight failed: required streams are not fresh");
            return rclcpp_action::GoalResponse::REJECT;
        }
        {
            std::lock_guard<std::mutex> lock(samples_mutex_);
            for (std::size_t index = 0; index < camera_topics_.size(); ++index) {
                const auto& receipts = image_receipts_[index];
                const auto span_ns = receipts.size() > 1 ? receipts.back() - receipts.front() : 0;
                const auto measured_fps = span_ns > 0 ?
                    static_cast<double>(receipts.size() - 1) * 1.0e9 / static_cast<double>(span_ns) : 0.0;
                if (span_ns < 1500000000LL ||
                    std::abs(measured_fps - camera_expected_fps_[index]) > camera_fps_tolerances_[index]) {
                    RCLCPP_ERROR(
                        get_logger(),
                        "preflight failed: camera %s measured %.3f FPS over %.3f seconds; expected %.3f +/- %.3f",
                        camera_topics_[index].c_str(), measured_fps,
                        static_cast<double>(span_ns) / 1.0e9,
                        camera_expected_fps_[index], camera_fps_tolerances_[index]);
                    return rclcpp_action::GoalResponse::REJECT;
                }
            }
        }
        if (!enough_disk(get_parameter("preflight_min_free_gib").as_double())) {
            RCLCPP_ERROR(get_logger(), "preflight failed: disk reserve");
            return rclcpp_action::GoalResponse::REJECT;
        }
        return rclcpp_action::GoalResponse::ACCEPT_AND_EXECUTE;
    }

    void start_recording(const std::shared_ptr<GoalHandleRecord> handle) {
        try {
            const auto goal = handle->get_goal();
            current_metadata_ = goal->metadata;
            current_id_ = uuid_to_string(current_metadata_.episode_id);
            current_goal_ = handle;
            current_staging_ = manager_->begin_episode(current_id_);

            rosbag2_storage::StorageOptions options;
            options.uri = (current_staging_ / "bag").string();
            options.storage_id = "mcap";
            options.max_bagfile_size = 0;
            options.max_bagfile_duration = 0;
            options.storage_config_uri = mcap_config_;
            writer_ = std::make_unique<rosbag2_cpp::Writer>();
            writer_->open(options);
            for (const auto& camera_topic : camera_topics_) {
                writer_->create_topic(topic(camera_topic, "sensor_msgs/msg/CompressedImage"));
            }
            writer_->create_topic(topic(joint_state_topic_, "sensor_msgs/msg/JointState"));
            writer_->create_topic(topic(action_topic_, "platform_control_interfaces/msg/JointIntent"));
            writer_->create_topic(topic("/platform/episode/metadata", "platform_episode_interfaces/msg/EpisodeMetadata"));
            writer_->create_topic(topic("/platform/episode/events", "platform_episode_interfaces/msg/EpisodeEvent"));
            writer_->create_topic(topic("/platform/control/safety_events", "platform_control_interfaces/msg/SafetyEvent"));
            writer_->create_topic(topic("/platform/control/command_rejections", "platform_control_interfaces/msg/CommandRejection"));

            writer_stop_ = false;
            writer_failed_ = false;
            current_writer_dropped_ = false;
            current_writer_error_ = false;
            queue_bytes_ = 0;
            writer_bytes_ = 0;
            writer_thread_ = std::thread([this]() { writer_loop(); });
            recording_started_ns_ = now().nanoseconds();
            ++recordings_started_;
            {
                // Make the pre-roll/live handoff atomic with the action
                // callback. This prevents the newest cached command from also
                // being appended as the first live command.
                std::lock_guard<std::mutex> lock(samples_mutex_);
                enqueue(serialize_message(
                    current_metadata_, "/platform/episode/metadata", recording_started_ns_,
                    recording_started_ns_), true);
                for (const auto& [message, receipt_ns] : recent_actions_) {
                    enqueue(serialize_message(
                        *message, action_topic_, receipt_ns, to_nanoseconds(message->issued_at)), true);
                }
                recording_ = true;
            }
            publish_state(platform_episode_interfaces::msg::EpisodeState::STATE_RECORDING, "recording");
            RCLCPP_INFO(get_logger(), "recording episode %s", current_id_.c_str());
        } catch (const std::exception& error) {
            recording_ = false;
            {
                std::lock_guard<std::mutex> lock(queue_mutex_);
                writer_stop_ = true;
                queue_cv_.notify_all();
            }
            if (writer_thread_.joinable()) writer_thread_.join();
            if (writer_) {
                try { writer_->close(); } catch (...) {}
                writer_.reset();
            }
            auto result = std::make_shared<RecordEpisode::Result>();
            result->request_id = handle->get_goal()->request_id;
            result->episode_id = handle->get_goal()->metadata.episode_id;
            result->complete = false;
            const auto retained = retain_rejected_partial(error.what());
            result->artifact_disposition = retained.empty() ? RecordEpisode::Result::ARTIFACT_NONE :
                RecordEpisode::Result::ARTIFACT_PARTIAL_RETAINED;
            result->artifact_id = retained.empty() ? "" : current_id_;
            result->artifact_uri = retained.string();
            result->reason = error.what();
            handle->abort(result);
            publish_state(platform_episode_interfaces::msg::EpisodeState::STATE_FAILED, error.what());
            current_goal_.reset();
            current_id_.clear();
            terminal_requested_ = false;
            cancel_requested_ = false;
        }
    }

    void enqueue(
        std::shared_ptr<rosbag2_storage::SerializedBagMessage> message,
        bool allow_before_recording = false) {
        const auto bytes = message->serialized_data ? message->serialized_data->buffer_length : 0U;
        std::lock_guard<std::mutex> lock(queue_mutex_);
        if ((!recording_ && !allow_before_recording) || writer_stop_ ||
            terminal_requested_ || cancel_requested_) return;
        if (queue_bytes_ + bytes > kWriterQueueCapacity) {
            fail_writer("writer queue exceeded 256 MiB", true);
            return;
        }
        queue_.push_back({std::move(message), bytes});
        queue_bytes_ += bytes;
        queue_cv_.notify_one();
    }

    void writer_loop() {
        while (true) {
            QueuedMessage item;
            {
                std::unique_lock<std::mutex> lock(queue_mutex_);
                queue_cv_.wait(lock, [this]() { return writer_stop_ || !queue_.empty(); });
                if (queue_.empty() && writer_stop_) break;
                item = std::move(queue_.front());
                queue_.pop_front();
                queue_bytes_ -= item.bytes;
            }
            try {
                writer_->write(item.message);
                writer_bytes_ += item.bytes;
            } catch (const std::exception& error) {
                fail_writer(error.what(), false);
            }
        }
    }

    void fail_writer(const std::string& reason, bool dropped) {
        if (!writer_failed_.exchange(true)) {
            if (dropped) {
                current_writer_dropped_ = true;
                ++writer_drops_;
            } else {
                current_writer_error_ = true;
                ++writer_errors_;
            }
            std::lock_guard<std::mutex> lock(writer_error_mutex_);
            writer_error_ = reason;
        }
    }

    std::string writer_failure_reason() {
        std::lock_guard<std::mutex> lock(writer_error_mutex_);
        return writer_error_;
    }

    void handle_mark(
        const platform_episode_interfaces::srv::MarkEpisode::Request& request,
        platform_episode_interfaces::srv::MarkEpisode::Response& response) {
        response.request_id = request.request_id;
        response.event_id = random_uuid();
        if (!recording_ || terminal_requested_ || cancel_requested_ ||
            uuid_to_string(request.episode_id) != current_id_) {
            response.accepted = false;
            response.reason = "episode is not recording";
            return;
        }
        auto event = make_event(request.mark, request.annotation, response.event_id);
        event_pub_->publish(event);
        enqueue(serialize_message(
            event, "/platform/episode/events", now().nanoseconds(),
            to_nanoseconds(event.header.stamp)));
        if (request.mark == platform_episode_interfaces::srv::MarkEpisode::Request::MARK_SUCCESS) {
            terminal_success_ = true;
            terminal_requested_ = true;
            finish_timer_->reset();
        } else if (request.mark == platform_episode_interfaces::srv::MarkEpisode::Request::MARK_FAILURE) {
            terminal_success_ = false;
            terminal_requested_ = true;
            finish_timer_->reset();
        }
        response.accepted = true;
    }

    platform_episode_interfaces::msg::EpisodeEvent make_event(
        uint8_t mark, const std::string& annotation,
        const unique_identifier_msgs::msg::UUID& event_id) {
        platform_episode_interfaces::msg::EpisodeEvent event;
        event.header.stamp = now();
        event.episode_id = current_metadata_.episode_id;
        event.event_id = event_id;
        event.source_id = "episode_recorder.keyboard";
        event.kind = platform_episode_interfaces::msg::EpisodeEvent::KIND_OPERATOR;
        event.event_code = mark;
        event.summary = mark == 0 ? "operator marked success" :
            (mark == 1 ? "operator marked failure" : "operator annotation");
        event.detail = annotation;
        return event;
    }

    void finish_recording(bool success, bool canceled, const std::string& reason) {
        if (!recording_ || finishing_.exchange(true)) return;
        recording_ = false;
        publish_state(platform_episode_interfaces::msg::EpisodeState::STATE_FINALIZING, "flushing MCAP");
        {
            std::lock_guard<std::mutex> lock(queue_mutex_);
            writer_stop_ = true;
            queue_cv_.notify_all();
        }
        if (writer_thread_.joinable()) writer_thread_.join();

        auto result = std::make_shared<RecordEpisode::Result>();
        result->request_id = current_goal_->get_goal()->request_id;
        result->episode_id = current_metadata_.episode_id;
        try {
            writer_->close();
            writer_.reset();
            fs::path mcap;
            std::size_t mcap_count = 0;
            for (const auto& entry : fs::recursive_directory_iterator(current_staging_)) {
                if (entry.is_regular_file() && entry.path().extension() == ".mcap") {
                    mcap = entry.path();
                    ++mcap_count;
                }
            }
            if (mcap_count != 1) throw std::runtime_error("episode does not contain exactly one MCAP");
            verify_mcap_readable(current_staging_ / "bag");
            const auto hash = sha256_file(mcap);
            write_manifest(current_staging_, hash, success, canceled, reason);
            const auto final = manager_->finalize_episode(current_id_);
            write_status(
                final,
                current_id_,
                success && !writer_failed_ ? "pending_validation" : "rejected",
                success && !writer_failed_ ? "awaiting automatic validation" : reason);
            result->complete = true;
            result->artifact_disposition = !canceled && !writer_failed_ ?
                RecordEpisode::Result::ARTIFACT_COMPLETE :
                RecordEpisode::Result::ARTIFACT_PARTIAL_RETAINED;
            result->artifact_id = current_id_;
            result->artifact_uri = final.string();
            result->content_hash = hash;
            result->reason = reason;
            if (canceled) current_goal_->canceled(result);
            else current_goal_->succeed(result);
            if (success && !writer_failed_) ++recordings_completed_;
            else ++recordings_rejected_;
            if (success && !writer_failed_) request_validation(hash);
            else publish_state(platform_episode_interfaces::msg::EpisodeState::STATE_FAILED, reason);
        } catch (const std::exception& error) {
            result->complete = false;
            const auto retained = retain_rejected_partial(error.what());
            result->artifact_disposition = retained.empty() ? RecordEpisode::Result::ARTIFACT_NONE :
                RecordEpisode::Result::ARTIFACT_PARTIAL_RETAINED;
            result->artifact_id = retained.empty() ? "" : current_id_;
            result->artifact_uri = retained.string();
            result->reason = error.what();
            current_goal_->abort(result);
            publish_state(platform_episode_interfaces::msg::EpisodeState::STATE_FAILED, error.what());
        }
        current_goal_.reset();
        current_id_.clear();
        terminal_requested_ = false;
        cancel_requested_ = false;
        finishing_ = false;
    }

    fs::path retain_rejected_partial(const std::string& reason) {
        if (current_id_.empty()) return {};
        try {
            fs::path final = fs::path(dataset_dir_) / "episodes" / current_id_;
            if (!fs::exists(final) && fs::exists(current_staging_)) {
                fs::path mcap;
                for (const auto& entry : fs::recursive_directory_iterator(current_staging_)) {
                    if (entry.is_regular_file() && entry.path().extension() == ".mcap") {
                        if (!mcap.empty()) {
                            mcap.clear();
                            break;
                        }
                        mcap = entry.path();
                    }
                }
                std::string hash;
                if (!mcap.empty()) {
                    try { hash = sha256_file(mcap); } catch (...) {}
                }
                write_manifest(current_staging_, hash, false, true, reason);
                final = manager_->finalize_episode(current_id_);
            }
            if (fs::exists(final)) {
                write_status(final, current_id_, "rejected", reason);
                return final;
            }
        } catch (const std::exception& nested) {
            RCLCPP_ERROR(get_logger(), "failed to retain rejected partial: %s", nested.what());
        }
        return {};
    }

    void verify_mcap_readable(const fs::path& bag) {
        rosbag2_cpp::Reader reader;
        rosbag2_storage::StorageOptions options;
        options.uri = bag.string();
        options.storage_id = "mcap";
        reader.open(options);
        std::size_t count = 0;
        while (reader.has_next()) {
            static_cast<void>(reader.read_next());
            ++count;
        }
        if (count == 0) throw std::runtime_error("MCAP contains no messages");
        reader.close();
    }

    void write_manifest(
        const fs::path& final, const std::string& hash, bool success, bool canceled,
        const std::string& reason) {
        nlohmann::json producers = nlohmann::json::array();
        for (const auto& producer : current_metadata_.producers) {
            producers.push_back({
                {"component_id", producer.component.component_id},
                {"name", producer.component.name},
                {"semantic_version", producer.component.semantic_version},
                {"source_revision", producer.component.source_revision},
                {"build_id", producer.component.build_id},
                {"configuration_hash", producer.configuration.content_hash},
                {"calibration_id", producer.calibration_id},
                {"calibration_hash", producer.calibration_hash}
            });
        }
        nlohmann::json manifest = {
            {"schema_version", "episode-manifest/v1"},
            {"episode_id", current_id_},
            {"artifact_id", current_id_},
            {"content_hash", hash},
            {"recording_profile_id", current_metadata_.recording_profile_id},
            {"recording_profile_hash", get_parameter("recording_profile_hash").as_string()},
            {"task_id", current_metadata_.task_id},
            {"task_catalog_hash", sha256_file(task_catalog_)},
            {"workcell_id", current_metadata_.workcell_id},
            {"configuration_hash", current_metadata_.configuration.content_hash},
            {"producers", producers},
            {"calibration_ids", current_metadata_.calibration_ids},
            {"started_ns", recording_started_ns_},
            {"finalized_ns", now().nanoseconds()},
            {"operator_success", success},
            {"canceled", canceled},
            {"writer_dropped", current_writer_dropped_.load()},
            {"writer_error", current_writer_error_.load()},
            {"reason", reason},
            {"storage_id", "mcap"}
        };
        std::ofstream output(final / "manifest.json");
        output << std::setw(2) << manifest << '\n';
    }

    void write_status(
        const fs::path& episode, const std::string& episode_id,
        const std::string& status, const std::string& reason) {
        const auto unix_seconds = std::chrono::duration<double>(
            std::chrono::system_clock::now().time_since_epoch()).count();
        nlohmann::json payload = {
            {"episode_id", episode_id},
            {"status", status},
            {"validated_at_unix", unix_seconds},
            {"reason", reason}
        };
        const auto temporary = episode / "status.json.tmp";
        {
            std::ofstream output(temporary);
            output << std::setw(2) << payload << '\n';
        }
        fs::rename(temporary, episode / "status.json");
    }

    void request_validation(const std::string& hash) {
        const auto validation_metadata = current_metadata_;
        const auto validation_id = current_id_;
        publish_state_for(validation_metadata, platform_episode_interfaces::msg::EpisodeState::STATE_VALIDATING, "validating raw episode");
        if (!validator_client_->wait_for_action_server(2s)) {
            write_status(
                fs::path(dataset_dir_) / "episodes" / validation_id,
                validation_id,
                "rejected", "automatic validator unavailable");
            publish_state_for(validation_metadata, platform_episode_interfaces::msg::EpisodeState::STATE_FAILED, "validator unavailable");
            return;
        }
        ValidateEpisode::Goal goal;
        goal.request_id = random_uuid();
        goal.episode_id = current_metadata_.episode_id;
        goal.artifact_id = validation_id;
        goal.content_hash = hash;
        rclcpp_action::Client<ValidateEpisode>::SendGoalOptions options;
        options.result_callback = [this, validation_metadata, validation_id](const auto& wrapped) {
            const bool valid = wrapped.code == rclcpp_action::ResultCode::SUCCEEDED &&
                wrapped.result && wrapped.result->valid;
            if (!valid) {
                const auto status_path = fs::path(dataset_dir_) / "episodes" / validation_id / "status.json";
                if (fs::is_regular_file(status_path)) {
                    std::ifstream input(status_path);
                    nlohmann::json status;
                    input >> status;
                    if (status.value("status", "") == "pending_validation") {
                        write_status(
                            status_path.parent_path(), validation_id, "rejected",
                            "automatic validation did not accept the episode");
                    }
                }
            }
            publish_state_for(validation_metadata, valid ? platform_episode_interfaces::msg::EpisodeState::STATE_VALIDATED :
                platform_episode_interfaces::msg::EpisodeState::STATE_FAILED,
                valid ? "episode accepted" : "episode rejected; explicit retry required");
        };
        validator_client_->async_send_goal(goal, options);
    }

    void publish_state(uint8_t state, const std::string& summary) {
        publish_state_for(current_metadata_, state, summary);
    }

    void publish_state_for(
        const platform_episode_interfaces::msg::EpisodeMetadata& metadata,
        uint8_t state, const std::string& summary) {
        platform_episode_interfaces::msg::EpisodeState message;
        message.header.stamp = now();
        message.episode_id = metadata.episode_id;
        message.task_id = metadata.task_id;
        message.state = state;
        message.summary = summary;
        recorder_state_ = state;
        state_pub_->publish(message);
    }

    RecordEpisode::Goal keyboard_goal() {
        RecordEpisode::Goal goal;
        goal.request_id = random_uuid();
        goal.metadata.episode_id = random_uuid();
        goal.metadata.workcell_id = get_parameter("workcell_id").as_string();
        goal.metadata.task_id = get_parameter("task_id").as_string();
        goal.metadata.recording_profile_id = get_parameter("recording_profile_id").as_string();
        goal.metadata.configuration.schema_id = "episode-recording";
        goal.metadata.configuration.schema_version = "1.0.0";
        goal.metadata.configuration.configuration_id = goal.metadata.recording_profile_id;
        goal.metadata.configuration.content_hash = get_parameter("configuration_hash").as_string();
        platform_common_interfaces::msg::ProvenanceReference producer;
        producer.component.component_id = "episode_recorder";
        producer.component.name = "Episode Recorder";
        producer.component.semantic_version = "0.2.0";
        producer.component.source_revision = get_parameter("source_revision").as_string();
        producer.component.build_id = producer.component.source_revision;
        producer.configuration = goal.metadata.configuration;
        producer.calibration_id = get_parameter("calibration_id").as_string();
        producer.calibration_hash = get_parameter("calibration_hash").as_string();
        goal.metadata.producers.push_back(producer);
        goal.metadata.calibration_ids.push_back(producer.calibration_id);
        return goal;
    }

    void on_key(episode_recorder::KeyCommand command) {
        if (command == episode_recorder::KeyCommand::kStart) {
            if (recording_) {
                RCLCPP_WARN(get_logger(), "already recording; use y or n to finish");
                return;
            }
            if (!record_client_->wait_for_action_server(1s)) {
                RCLCPP_ERROR(get_logger(), "record action unavailable");
                return;
            }
            record_client_->async_send_goal(keyboard_goal());
        } else if (command == episode_recorder::KeyCommand::kSuccess ||
                   command == episode_recorder::KeyCommand::kFailure ||
                   command == episode_recorder::KeyCommand::kAnnotate) {
            platform_episode_interfaces::srv::MarkEpisode::Request request;
            request.request_id = random_uuid();
            request.episode_id = current_metadata_.episode_id;
            request.source_id = "episode_recorder.keyboard";
            request.mark = command == episode_recorder::KeyCommand::kSuccess ? 0 :
                (command == episode_recorder::KeyCommand::kFailure ? 1 : 2);
            request.annotation = command == episode_recorder::KeyCommand::kAnnotate ?
                "operator annotation" : "";
            platform_episode_interfaces::srv::MarkEpisode::Response response;
            handle_mark(request, response);
        } else if (command == episode_recorder::KeyCommand::kQuit) {
            shutdown_requested_ = true;
            if (recording_ && !terminal_requested_) {
                cancel_requested_ = true;
                finish_timer_->reset();
            }
        }
    }

    void finish_requested_recording() {
        if (!recording_) return;
        if (writer_failed_) finish_recording(false, false, writer_failure_reason());
        else if (cancel_requested_) finish_recording(false, true, "recording canceled");
        else if (terminal_requested_) {
            finish_recording(terminal_success_, false,
                terminal_success_ ? "operator marked success" : "operator marked failure");
        }
    }

    void monitor() {
        if (recording_ && !enough_disk(get_parameter("runtime_reserve_gib").as_double())) {
            fail_writer("disk space crossed runtime reserve", false);
        }
        if (recording_ && current_goal_) {
            auto feedback = std::make_shared<RecordEpisode::Feedback>();
            feedback->episode_id = current_metadata_.episode_id;
            feedback->state = platform_episode_interfaces::msg::EpisodeState::STATE_RECORDING;
            feedback->elapsed = static_cast<builtin_interfaces::msg::Duration>(rclcpp::Duration(
                std::chrono::nanoseconds(now().nanoseconds() - recording_started_ns_)));
            feedback->bytes_recorded = writer_bytes_.load();
            feedback->summary = "recording";
            current_goal_->publish_feedback(feedback);
        }
        finish_requested_recording();
        if (shutdown_requested_ && !recording_ && !finishing_) rclcpp::shutdown();
        publish_runtime_metrics();
    }

    void publish_runtime_metrics() {
        nlohmann::json payload = {
            {"profile", get_parameter("recording_profile_id").as_string()},
            {"state", recorder_state_.load()},
            {"writer_queue_bytes", queue_bytes_.load()},
            {"writer_drops", writer_drops_.load()},
            {"writer_errors", writer_errors_.load()},
            {"recordings_started", recordings_started_.load()},
            {"recordings_completed", recordings_completed_.load()},
            {"recordings_rejected", recordings_rejected_.load()}
        };
        std_msgs::msg::String message;
        message.data = payload.dump();
        metrics_pub_->publish(message);
    }

    std::string dataset_dir_;
    std::vector<std::string> camera_topics_;
    std::vector<double> camera_expected_fps_;
    std::vector<double> camera_fps_tolerances_;
    std::string joint_state_topic_;
    std::string action_topic_;
    std::string mcap_config_;
    std::string recording_profiles_;
    std::string task_catalog_;
    std::unique_ptr<episode_recorder::EpisodeManager> manager_;

    std::atomic<bool> recording_{false};
    std::atomic<bool> finishing_{false};
    std::atomic<bool> writer_stop_{false};
    std::atomic<bool> writer_failed_{false};
    std::atomic<bool> current_writer_dropped_{false};
    std::atomic<bool> current_writer_error_{false};
    std::atomic<bool> terminal_requested_{false};
    std::atomic<bool> terminal_success_{false};
    std::atomic<bool> cancel_requested_{false};
    std::atomic<bool> shutdown_requested_{false};
    std::atomic<std::size_t> queue_bytes_{0};
    std::atomic<uint64_t> writer_bytes_{0};
    std::atomic<uint64_t> writer_drops_{0};
    std::atomic<uint64_t> writer_errors_{0};
    std::atomic<uint64_t> recordings_started_{0};
    std::atomic<uint64_t> recordings_completed_{0};
    std::atomic<uint64_t> recordings_rejected_{0};
    std::atomic<uint8_t> recorder_state_{platform_episode_interfaces::msg::EpisodeState::STATE_UNKNOWN};
    std::vector<std::shared_ptr<std::atomic<int64_t>>> last_camera_ns_;
    std::atomic<int64_t> last_state_ns_{0};
    std::atomic<int64_t> last_action_ns_{0};
    int64_t recording_started_ns_{0};
    std::string writer_error_;
    std::mutex writer_error_mutex_;
    std::string current_id_;
    fs::path current_staging_;
    platform_episode_interfaces::msg::EpisodeMetadata current_metadata_;
    std::shared_ptr<GoalHandleRecord> current_goal_;

    std::unique_ptr<rosbag2_cpp::Writer> writer_;
    std::thread writer_thread_;
    std::mutex queue_mutex_;
    std::condition_variable queue_cv_;
    std::deque<QueuedMessage> queue_;
    std::mutex samples_mutex_;
    std::vector<std::deque<int64_t>> image_receipts_;
    std::deque<std::pair<platform_control_interfaces::msg::JointIntent::ConstSharedPtr, int64_t>>
        recent_actions_;

    std::vector<rclcpp::Subscription<sensor_msgs::msg::CompressedImage>::SharedPtr> image_subscriptions_;
    rclcpp::Subscription<sensor_msgs::msg::JointState>::SharedPtr state_sub_;
    rclcpp::Subscription<platform_control_interfaces::msg::JointIntent>::SharedPtr action_sub_;
    rclcpp::Subscription<platform_control_interfaces::msg::SafetyEvent>::SharedPtr safety_sub_;
    rclcpp::Subscription<platform_control_interfaces::msg::CommandRejection>::SharedPtr rejection_sub_;
    rclcpp::Publisher<platform_episode_interfaces::msg::EpisodeState>::SharedPtr state_pub_;
    rclcpp::Publisher<platform_episode_interfaces::msg::EpisodeEvent>::SharedPtr event_pub_;
    rclcpp::Publisher<std_msgs::msg::String>::SharedPtr metrics_pub_;
    rclcpp::Service<platform_episode_interfaces::srv::MarkEpisode>::SharedPtr mark_service_;
    rclcpp_action::Server<RecordEpisode>::SharedPtr record_server_;
    rclcpp_action::Client<RecordEpisode>::SharedPtr record_client_;
    rclcpp_action::Client<ValidateEpisode>::SharedPtr validator_client_;
    rclcpp::TimerBase::SharedPtr monitor_timer_;
    rclcpp::TimerBase::SharedPtr finish_timer_;
    std::unique_ptr<episode_recorder::KeyboardHandler> keyboard_;
};

int main(int argc, char** argv) {
    rclcpp::init(argc, argv);
    rclcpp::executors::MultiThreadedExecutor executor;
    // Keep an owning reference for the full executor lifetime. Passing a
    // temporary here can leave discoverable DDS entities whose callbacks are
    // no longer serviced by the executor.
    auto node = std::make_shared<RecorderNode>();
    executor.add_node(node);
    executor.spin();
    executor.remove_node(node);
    node.reset();
    rclcpp::shutdown();
    return 0;
}
