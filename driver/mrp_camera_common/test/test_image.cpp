#include <mrp_camera_common/heartbeat.hpp>
#include <mrp_camera_common/image.hpp>

#include <gtest/gtest.h>
#include <opencv2/imgcodecs.hpp>

#include <cstdio>
#include <string>
#include <sys/stat.h>
#include <unistd.h>

using mrp_camera_common::center_crop_for_aspect;
using mrp_camera_common::encode_jpeg;
using mrp_camera_common::fit_to_size;

TEST(Image, JpegFormatMatchesRecorderContract) {
  // The recorder only accepts "jpeg"/"jpg".
  EXPECT_STREQ(mrp_camera_common::JPEG_FORMAT, "jpeg");
}

TEST(Image, EncodesBgrJpegThatDecodesToTheSameColor) {
  const cv::Mat frame(32, 32, CV_8UC3, cv::Scalar(20, 100, 200));
  std::vector<std::uint8_t> encoded;
  ASSERT_TRUE(encode_jpeg(frame, 90, encoded));
  ASSERT_GT(encoded.size(), 4U);
  EXPECT_EQ(encoded[0], 0xFF);
  EXPECT_EQ(encoded[1], 0xD8);
  const cv::Mat decoded = cv::imdecode(encoded, cv::IMREAD_COLOR);
  ASSERT_EQ(decoded.size(), frame.size());
  const cv::Vec3b &center = decoded.at<cv::Vec3b>(16, 16);
  EXPECT_NEAR(center[0], 20, 10);
  EXPECT_NEAR(center[1], 100, 10);
  EXPECT_NEAR(center[2], 200, 10);
}

TEST(Image, MonoIsEncodedAsThreeChannels) {
  const cv::Mat frame(16, 16, CV_8UC1, cv::Scalar(128));
  std::vector<std::uint8_t> encoded;
  ASSERT_TRUE(encode_jpeg(frame, 90, encoded));
  const cv::Mat decoded = cv::imdecode(encoded, cv::IMREAD_UNCHANGED);
  EXPECT_EQ(decoded.channels(), 3);
}

TEST(Image, EncodesStridedView) {
  const cv::Mat big(40, 40, CV_8UC3, cv::Scalar(1, 2, 3));
  const cv::Mat view = big(cv::Rect(5, 5, 20, 10));
  std::vector<std::uint8_t> encoded;
  ASSERT_TRUE(encode_jpeg(view, 90, encoded));
  EXPECT_EQ(cv::imdecode(encoded, cv::IMREAD_COLOR).size(), cv::Size(20, 10));
}

TEST(Image, RejectsInvalidJpegInput) {
  std::vector<std::uint8_t> encoded;
  EXPECT_FALSE(encode_jpeg(cv::Mat(), 90, encoded));
  EXPECT_FALSE(encode_jpeg(cv::Mat(4, 4, CV_16UC1, cv::Scalar(1)), 90, encoded));
  EXPECT_FALSE(encode_jpeg(cv::Mat(4, 4, CV_8UC3), 0, encoded));
  EXPECT_FALSE(encode_jpeg(cv::Mat(4, 4, CV_8UC3), 101, encoded));
}

TEST(Image, CropKeepsAspectRatioOfTarget) {
  // 5:4 sensor to 4:3 output: cut top and bottom.
  EXPECT_EQ(center_crop_for_aspect({1280, 1024}, {640, 480}), cv::Rect(0, 32, 1280, 960));
  // 16:9 sensor to 4:3 output: cut left and right.
  EXPECT_EQ(center_crop_for_aspect({1920, 1080}, {640, 480}), cv::Rect(240, 0, 1440, 1080));
  // Same aspect: nothing is cut.
  EXPECT_EQ(center_crop_for_aspect({1280, 960}, {640, 480}), cv::Rect(0, 0, 1280, 960));
  EXPECT_EQ(center_crop_for_aspect({0, 960}, {640, 480}), cv::Rect());
  EXPECT_EQ(center_crop_for_aspect({1280, 960}, {640, 0}), cv::Rect());
}

TEST(Image, FitDoesNotDistort) {
  // Left/right quarters black, centre white, on a 16:9 image: after fitting to 4:3
  // the black edges are cropped away instead of squeezed in.
  cv::Mat image(90, 160, CV_8UC3, cv::Scalar(0, 0, 0));
  image(cv::Rect(20, 0, 120, 90)).setTo(cv::Scalar(255, 255, 255));
  const cv::Mat out = fit_to_size(image, {80, 60});
  ASSERT_EQ(out.size(), cv::Size(80, 60));
  EXPECT_GT(out.at<cv::Vec3b>(30, 1)[0], 200);
  EXPECT_GT(out.at<cv::Vec3b>(30, 78)[0], 200);
}

TEST(Image, FitReturnsInputWhenAlreadyRightSize) {
  const cv::Mat image(48, 64, CV_8UC1, cv::Scalar(7));
  const cv::Mat out = fit_to_size(image, {64, 48});
  EXPECT_EQ(out.data, image.data);
}

TEST(Image, FitUpscalesAndHandlesMono) {
  const cv::Mat image(30, 40, CV_8UC1, cv::Scalar(9));
  const cv::Mat out = fit_to_size(image, {80, 60});
  EXPECT_EQ(out.size(), cv::Size(80, 60));
  EXPECT_EQ(out.type(), CV_8UC1);
  EXPECT_TRUE(fit_to_size(cv::Mat(), {80, 60}).empty());
  EXPECT_TRUE(fit_to_size(image, {0, 60}).empty());
}

TEST(Heartbeat, DisabledWithoutPath) {
  const mrp_camera_common::HeartbeatFile heartbeat("");
  EXPECT_FALSE(heartbeat.enabled());
  EXPECT_FALSE(heartbeat.touch());
}

TEST(Heartbeat, CreatesAndRefreshesFile) {
  const std::string path = ::testing::TempDir() + "/mrp_heartbeat_" + std::to_string(::getpid());
  std::remove(path.c_str());
  const mrp_camera_common::HeartbeatFile heartbeat(path);
  ASSERT_TRUE(heartbeat.touch());
  struct stat info {};
  ASSERT_EQ(::stat(path.c_str(), &info), 0);
  EXPECT_TRUE(heartbeat.touch());
  std::remove(path.c_str());
}

TEST(Heartbeat, ReportsUnwritablePath) {
  const mrp_camera_common::HeartbeatFile heartbeat("/nonexistent-dir/heartbeat");
  EXPECT_FALSE(heartbeat.touch());
}
