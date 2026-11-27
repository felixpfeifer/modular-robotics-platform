#include <camera_genicam/genicam_utils.hpp>

#include <gtest/gtest.h>

#include <cstddef>
#include <cstdint>
#include <vector>

using camera_genicam::CameraEntry;

TEST(GenicamUtils, PrefersBayerOverRgbAndMono) {
  std::string error;
  EXPECT_EQ(camera_genicam::choose_pixel_format({"Mono8", "BGR8", "BayerGR8"}, "", error),
            "BayerGR8");
  EXPECT_EQ(camera_genicam::choose_pixel_format({"Mono8", "RGB8"}, "", error), "RGB8");
  EXPECT_EQ(camera_genicam::choose_pixel_format({"Mono12", "Mono8"}, "", error), "Mono8");
}

TEST(GenicamUtils, HonoursRequestedFormatOnlyWhenOfferedAndSupported) {
  std::string error;
  EXPECT_EQ(camera_genicam::choose_pixel_format({"Mono8", "BGR8"}, "BGR8", error), "BGR8");
  EXPECT_EQ(camera_genicam::choose_pixel_format({"Mono8"}, "BGR8", error), "");
  EXPECT_NE(error.find("offers: Mono8"), std::string::npos);
  EXPECT_EQ(camera_genicam::choose_pixel_format({"Mono12p"}, "Mono12p", error), "");
  EXPECT_NE(error.find("not supported"), std::string::npos);
}

TEST(GenicamUtils, FailsWhenNothingIsConvertible) {
  std::string error;
  EXPECT_EQ(camera_genicam::choose_pixel_format({"Mono12p", "Coord3D_C16"}, "", error), "");
  EXPECT_NE(error.find("Mono12p, Coord3D_C16"), std::string::npos);
}

// ---- Conversion -----------------------------------------------------------------

TEST(GenicamUtils, WrapsMono8AndBgr8WithoutCopy) {
  std::vector<uint8_t> mono(std::size_t{4} * 2, 7);
  cv::Mat out;
  ASSERT_EQ(camera_genicam::to_8bit_image(mono.data(), mono.size(), 4, 2, "Mono8", out), "");
  EXPECT_EQ(out.type(), CV_8UC1);
  EXPECT_EQ(out.data, mono.data());

  std::vector<uint8_t> bgr(std::size_t{4} * 2 * 3, 9);
  ASSERT_EQ(camera_genicam::to_8bit_image(bgr.data(), bgr.size(), 4, 2, "BGR8", out), "");
  EXPECT_EQ(out.type(), CV_8UC3);
  EXPECT_EQ(out.data, bgr.data());
}

TEST(GenicamUtils, SwapsRgbToBgr) {
  const std::vector<uint8_t> rgb = {255, 0, 0, 255, 0, 0}; // two red pixels
  cv::Mat out;
  ASSERT_EQ(camera_genicam::to_8bit_image(rgb.data(), rgb.size(), 2, 1, "RGB8", out), "");
  EXPECT_EQ(out.at<cv::Vec3b>(0, 0), cv::Vec3b(0, 0, 255));
}

TEST(GenicamUtils, ScalesMono12ToEightBits) {
  const std::vector<uint16_t> mono12 = {4095, 0, 2048, 16};
  cv::Mat out;
  ASSERT_EQ(camera_genicam::to_8bit_image(mono12.data(), mono12.size() * 2, 4, 1, "Mono12", out),
            "");
  ASSERT_EQ(out.type(), CV_8UC1);
  EXPECT_EQ(out.at<uint8_t>(0, 0), 255);
  EXPECT_EQ(out.at<uint8_t>(0, 1), 0);
  EXPECT_EQ(out.at<uint8_t>(0, 2), 128);
  EXPECT_EQ(out.at<uint8_t>(0, 3), 1);
}

// A uniformly red scene seen through each Bayer pattern must come out red: this
// pins the GenICam -> OpenCV pattern mapping, which is easy to get wrong.
class BayerPattern : public ::testing::TestWithParam<std::pair<const char *, const char *>> {};

TEST_P(BayerPattern, DemosaicsRedSceneToRed) {
  const std::string format = GetParam().first;
  const std::string pattern = GetParam().second; // colours of the top-left 2x2 cell, row-major
  constexpr int w = 8;
  constexpr int h = 8;
  std::vector<uint8_t> mosaic(static_cast<std::size_t>(w) * static_cast<std::size_t>(h));
  for (int y = 0; y < h; ++y) {
    for (int x = 0; x < w; ++x) {
      const char colour = pattern[static_cast<size_t>((y % 2) * 2 + (x % 2))];
      mosaic[(static_cast<std::size_t>(y) * static_cast<std::size_t>(w)) +
             static_cast<std::size_t>(x)] = colour == 'R' ? 200 : 0;
    }
  }
  cv::Mat out;
  ASSERT_EQ(camera_genicam::to_8bit_image(mosaic.data(), mosaic.size(), w, h, format, out), "");
  ASSERT_EQ(out.type(), CV_8UC3);
  const cv::Vec3b px = out.at<cv::Vec3b>(4, 4); // BGR
  EXPECT_GT(px[2], 150) << format;
  EXPECT_LT(px[1], 50) << format;
  EXPECT_LT(px[0], 50) << format;
}

INSTANTIATE_TEST_SUITE_P(AllPatterns, BayerPattern,
                         ::testing::Values(std::make_pair("BayerRG8", "RGGB"),
                                           std::make_pair("BayerBG8", "BGGR"),
                                           std::make_pair("BayerGR8", "GRBG"),
                                           std::make_pair("BayerGB8", "GBRG")));

TEST(GenicamUtils, ConvertsYuv422ToBgr) {
  // Mid-grey in YUYV: Y=128, U=V=128.
  const std::vector<uint8_t> yuyv = {128, 128, 128, 128};
  cv::Mat out;
  ASSERT_EQ(camera_genicam::to_8bit_image(yuyv.data(), yuyv.size(), 2, 1, "YUV422_8", out), "");
  ASSERT_EQ(out.type(), CV_8UC3);
  EXPECT_NEAR(out.at<cv::Vec3b>(0, 0)[1], 128, 3);
}

TEST(GenicamUtils, RejectsShortOrUnknownFrames) {
  std::vector<uint8_t> data(10);
  cv::Mat out;
  EXPECT_NE(camera_genicam::to_8bit_image(data.data(), data.size(), 4, 4, "Mono8", out), "");
  EXPECT_NE(camera_genicam::to_8bit_image(data.data(), data.size(), 2, 1, "Mono12p", out), "");
  EXPECT_NE(camera_genicam::to_8bit_image(nullptr, 0, 2, 1, "Mono8", out), "");
}

// ---- Camera selection -----------------------------------------------------------

namespace {
std::vector<CameraEntry> cameras() {
  return {
      {"Basler-acA1300-60gc-21234567", "Basler", "acA1300-60gc", "21234567", "192.168.10.11",
       "GigEVision"},
      {"Allied Vision-1AB22C-0001", "Allied Vision", "Alvium 1800 U-240c", "0001", "usb:2-1",
       "USB3Vision"},
      {"Basler-acA2440-20gm-22000001", "Basler", "acA2440-20gm", "22000001", "192.168.10.12",
       "GigEVision"},
  };
}
} // namespace

TEST(GenicamUtils, SelectsFirstCameraOfTransport) {
  std::string error;
  EXPECT_EQ(camera_genicam::select_camera(cameras(), "", "", "", error), 0);
  EXPECT_EQ(camera_genicam::select_camera(cameras(), "USB3Vision", "", "", error), 1);
}

TEST(GenicamUtils, SelectsBySerialIdOrAddress) {
  std::string error;
  EXPECT_EQ(camera_genicam::select_camera(cameras(), "", "22000001", "", error), 2);
  EXPECT_EQ(camera_genicam::select_camera(cameras(), "", "", "Basler-acA2440-20gm-22000001", error),
            2);
  EXPECT_EQ(camera_genicam::select_camera(cameras(), "GigEVision", "", "192.168.10.12", error), 2);
}

TEST(GenicamUtils, SerialMustMatchTransport) {
  std::string error;
  EXPECT_EQ(camera_genicam::select_camera(cameras(), "GigEVision", "0001", "", error), -1);
  EXPECT_NE(error.find("serial_number '0001'"), std::string::npos);
}

TEST(GenicamUtils, ExplainsMissingCameras) {
  std::string error;
  EXPECT_EQ(camera_genicam::select_camera({}, "GigEVision", "", "", error), -1);
  EXPECT_EQ(error, "no GigEVision camera found");
  EXPECT_EQ(camera_genicam::select_camera(cameras(), "", "", "10.0.0.1", error), -1);
  EXPECT_NE(error.find("'10.0.0.1'"), std::string::npos);
}

TEST(GenicamUtils, MapsTransportNames) {
  std::string protocol;
  EXPECT_TRUE(camera_genicam::transport_protocol("gige", protocol));
  EXPECT_EQ(protocol, "GigEVision");
  EXPECT_TRUE(camera_genicam::transport_protocol("any", protocol));
  EXPECT_EQ(protocol, "");
  EXPECT_FALSE(camera_genicam::transport_protocol("firewire", protocol));
}

// ---- Feature syntax -------------------------------------------------------------

TEST(GenicamUtils, ParsesFeatureAssignmentsAndCommands) {
  camera_genicam::FeatureSetting f;
  ASSERT_EQ(camera_genicam::parse_feature(" BinningHorizontal = 2 ", f), "");
  EXPECT_EQ(f.name, "BinningHorizontal");
  EXPECT_EQ(f.value, "2");
  EXPECT_FALSE(f.is_command);

  ASSERT_EQ(camera_genicam::parse_feature("DeviceReset", f), "");
  EXPECT_TRUE(f.is_command);

  ASSERT_EQ(camera_genicam::parse_feature("DeviceUserID=top camera", f), "");
  EXPECT_EQ(f.value, "top camera");
}

TEST(GenicamUtils, RejectsMalformedFeatures) {
  camera_genicam::FeatureSetting f;
  EXPECT_NE(camera_genicam::parse_feature("=2", f), "");
  EXPECT_NE(camera_genicam::parse_feature("Gain=", f), "");
  EXPECT_NE(camera_genicam::parse_feature("R[0x100]=1", f), "");
  EXPECT_NE(camera_genicam::parse_feature("Exposure Time=1", f), "");
}
