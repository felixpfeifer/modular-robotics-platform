#include <camera_realsense/image_utils.hpp>
#include <limits>

#include <gtest/gtest.h>
#include <opencv2/imgcodecs.hpp>

using camera_realsense::depth_to_millimetres;
using camera_realsense::encode_depth_png;
using camera_realsense::stamp_from_milliseconds;

TEST(ImageUtils, DepthFormatFollowsImageTransportConvention) {
  EXPECT_STREQ(camera_realsense::DEPTH_FORMAT, "16UC1; png compressed 16UC1");
}

TEST(ImageUtils, DepthPngRoundTripIsLossless) {
  cv::Mat depth(48, 64, CV_16UC1);
  cv::randu(depth, cv::Scalar(0), cv::Scalar(65535));
  std::vector<uchar> encoded;

  ASSERT_TRUE(encode_depth_png(depth, 1, encoded));
  const cv::Mat decoded = cv::imdecode(encoded, cv::IMREAD_UNCHANGED);
  ASSERT_EQ(decoded.type(), CV_16UC1);
  ASSERT_EQ(decoded.size(), depth.size());
  EXPECT_EQ(cv::countNonZero(decoded != depth), 0);
}

TEST(ImageUtils, RejectsInvalidDepthInput) {
  std::vector<uchar> encoded;
  EXPECT_FALSE(encode_depth_png(cv::Mat(), 1, encoded));
  EXPECT_FALSE(encode_depth_png(cv::Mat(4, 4, CV_8UC3), 1, encoded));
}

TEST(ImageUtils, MillimetreScaleIsCopiedUnchanged) {
  cv::Mat raw(2, 2, CV_16UC1);
  raw.at<uint16_t>(0, 0) = 0;
  raw.at<uint16_t>(0, 1) = 500;
  raw.at<uint16_t>(1, 0) = 1234;
  raw.at<uint16_t>(1, 1) = 65535;

  const cv::Mat mm = depth_to_millimetres(raw, 0.001F, 0);
  ASSERT_EQ(mm.type(), CV_16UC1);
  EXPECT_EQ(cv::countNonZero(mm != raw), 0);
  EXPECT_NE(mm.data, raw.data); // must not alias the librealsense buffer
}

TEST(ImageUtils, SubMillimetreScaleIsRescaled) {
  // L515-style 0.25 mm units: 4000 units = 1000 mm.
  cv::Mat raw(1, 2, CV_16UC1);
  raw.at<uint16_t>(0, 0) = 4000;
  raw.at<uint16_t>(0, 1) = 3; // 0.75 mm rounds to 1
  const cv::Mat mm = depth_to_millimetres(raw, 0.00025F, 0);
  EXPECT_EQ(mm.at<uint16_t>(0, 0), 1000);
  EXPECT_EQ(mm.at<uint16_t>(0, 1), 1);
}

TEST(ImageUtils, MaxDepthClipsToInvalid) {
  cv::Mat raw(1, 3, CV_16UC1);
  raw.at<uint16_t>(0, 0) = 999;
  raw.at<uint16_t>(0, 1) = 1000;
  raw.at<uint16_t>(0, 2) = 1001;
  const cv::Mat mm = depth_to_millimetres(raw, 0.001F, 1000);
  EXPECT_EQ(mm.at<uint16_t>(0, 0), 999);
  EXPECT_EQ(mm.at<uint16_t>(0, 1), 1000);
  EXPECT_EQ(mm.at<uint16_t>(0, 2), 0);
}

TEST(ImageUtils, DepthConversionRejectsBadInput) {
  EXPECT_TRUE(depth_to_millimetres(cv::Mat(), 0.001F, 0).empty());
  EXPECT_TRUE(depth_to_millimetres(cv::Mat(2, 2, CV_16UC1), 0.0F, 0).empty());
  EXPECT_TRUE(depth_to_millimetres(cv::Mat(2, 2, CV_8UC1), 0.001F, 0).empty());
}

TEST(ImageUtils, ConvertsMillisecondTimestamps) {
  const auto s = stamp_from_milliseconds(1700000000123.456);
  ASSERT_TRUE(s);
  EXPECT_EQ(s->sec, 1700000000);
  EXPECT_NEAR(static_cast<double>(s->nanosec), 123456000.0, 1000.0);

  const auto zero = stamp_from_milliseconds(0.0);
  ASSERT_TRUE(zero);
  EXPECT_EQ(zero->sec, 0);
  EXPECT_EQ(zero->nanosec, 0U);
}

TEST(ImageUtils, RejectsUnrepresentableTimestamps) {
  EXPECT_FALSE(stamp_from_milliseconds(-1.0));
  EXPECT_FALSE(stamp_from_milliseconds(std::numeric_limits<double>::quiet_NaN()));
  EXPECT_FALSE(stamp_from_milliseconds(std::numeric_limits<double>::infinity()));
  EXPECT_FALSE(stamp_from_milliseconds(2147483648000.0));
}
