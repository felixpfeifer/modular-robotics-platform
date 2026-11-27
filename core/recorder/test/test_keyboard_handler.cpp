#include <gtest/gtest.h>
#include <atomic>
#include <chrono>
#include <thread>
#include "episode_recorder/keyboard_handler.hpp"

using episode_recorder::KeyCommand;
using episode_recorder::KeyboardHandler;

class KeyboardHandlerTest : public ::testing::Test {
protected:
    std::atomic<KeyCommand> last_cmd_{KeyCommand::kNone};
    int call_count_ = 0;
};

TEST_F(KeyboardHandlerTest, InjectStart) {
    KeyboardHandler handler([this](KeyCommand cmd) {
        last_cmd_ = cmd;
        ++call_count_;
    });

    handler.inject_command(KeyCommand::kStart);
    EXPECT_EQ(last_cmd_.load(), KeyCommand::kStart);
    EXPECT_EQ(call_count_, 1);
}

TEST_F(KeyboardHandlerTest, InjectSuccess) {
    KeyboardHandler handler([this](KeyCommand cmd) {
        last_cmd_ = cmd;
        ++call_count_;
    });

    handler.inject_command(KeyCommand::kSuccess);
    EXPECT_EQ(last_cmd_.load(), KeyCommand::kSuccess);
}

TEST_F(KeyboardHandlerTest, InjectFailure) {
    KeyboardHandler handler([this](KeyCommand cmd) {
        last_cmd_ = cmd;
        ++call_count_;
    });

    handler.inject_command(KeyCommand::kFailure);
    EXPECT_EQ(last_cmd_.load(), KeyCommand::kFailure);
}

TEST_F(KeyboardHandlerTest, InjectQuit) {
    KeyboardHandler handler([this](KeyCommand cmd) {
        last_cmd_ = cmd;
        ++call_count_;
    });

    handler.inject_command(KeyCommand::kQuit);
    EXPECT_EQ(last_cmd_.load(), KeyCommand::kQuit);
}

TEST_F(KeyboardHandlerTest, MultipleInjectionsCallCallbackMultipleTimes) {
    KeyboardHandler handler([this](KeyCommand cmd) {
        last_cmd_ = cmd;
        ++call_count_;
    });

    handler.inject_command(KeyCommand::kStart);
    handler.inject_command(KeyCommand::kSuccess);
    handler.inject_command(KeyCommand::kQuit);
    EXPECT_EQ(call_count_, 3);
    EXPECT_EQ(last_cmd_.load(), KeyCommand::kQuit);
}

TEST_F(KeyboardHandlerTest, StopIsIdempotent) {
    KeyboardHandler handler([this](KeyCommand cmd) {
        last_cmd_ = cmd;
    });

    // Should not crash or hang
    handler.stop();
    handler.stop();
}
