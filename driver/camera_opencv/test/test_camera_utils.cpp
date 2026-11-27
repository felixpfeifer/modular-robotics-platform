#include <camera_opencv/camera_utils.hpp>

#include <gtest/gtest.h>

TEST(CameraUtils, UsesCapabilitiesOfTheIndividualV4l2Node) {
  v4l2_capability capability{};
  capability.capabilities = V4L2_CAP_VIDEO_CAPTURE;
  EXPECT_TRUE(camera_opencv::is_video_capture_device(capability));

  capability.capabilities |= V4L2_CAP_DEVICE_CAPS;
  capability.device_caps = V4L2_CAP_META_CAPTURE;
  EXPECT_FALSE(camera_opencv::is_video_capture_device(capability));

  capability.device_caps = V4L2_CAP_VIDEO_CAPTURE | V4L2_CAP_STREAMING;
  EXPECT_TRUE(camera_opencv::is_video_capture_device(capability));
}

TEST(CameraUtils, RecognizesColorPixelFormats) {
  EXPECT_TRUE(camera_opencv::is_color_pixel_format(V4L2_PIX_FMT_YUYV));
  EXPECT_TRUE(camera_opencv::is_color_pixel_format(V4L2_PIX_FMT_UYVY));
  EXPECT_TRUE(camera_opencv::is_color_pixel_format(V4L2_PIX_FMT_MJPEG));
  EXPECT_TRUE(camera_opencv::is_color_pixel_format(V4L2_PIX_FMT_RGB24));
  EXPECT_TRUE(camera_opencv::is_color_pixel_format(V4L2_PIX_FMT_BGR24));
  EXPECT_TRUE(camera_opencv::is_color_pixel_format(V4L2_PIX_FMT_NV12));
}

TEST(CameraUtils, RejectsNonColorAndUnknownPixelFormats) {
  EXPECT_FALSE(camera_opencv::is_color_pixel_format(V4L2_PIX_FMT_Z16));
  EXPECT_FALSE(camera_opencv::is_color_pixel_format(V4L2_PIX_FMT_GREY));
  EXPECT_FALSE(camera_opencv::is_color_pixel_format(0));
}

TEST(CameraUtils, OnlyFixedPortsAreBuiltIn) {
  EXPECT_TRUE(camera_opencv::is_builtin_removable_value("fixed"));
  EXPECT_FALSE(camera_opencv::is_builtin_removable_value("removable"));
  // Desktop and Jetson ports often cannot tell; a plugged-in camera must still be found.
  EXPECT_FALSE(camera_opencv::is_builtin_removable_value("unknown"));
}

TEST(CameraUtils, PrefersRealSenseThenFirstExternalCamera) {
  using camera_opencv::DeviceCandidate;
  const std::vector<DeviceCandidate> devices = {
      {"/dev/video0", "Integrated Camera", true},
      {"/dev/video2", "USB Webcam", false},
      {"/dev/video4", "Intel(R) RealSense(TM) Depth Ca", false},
      {"/dev/video6", "Other Webcam", false},
  };
  ASSERT_TRUE(camera_opencv::choose_device(devices));
  EXPECT_EQ(camera_opencv::choose_device(devices)->path, "/dev/video4");

  const std::vector<DeviceCandidate> webcams(devices.begin(), devices.begin() + 2);
  EXPECT_EQ(camera_opencv::choose_device(webcams)->path, "/dev/video2");
}

TEST(CameraUtils, NeverChoosesBuiltInCamera) {
  EXPECT_FALSE(camera_opencv::choose_device({{"/dev/video0", "Integrated Camera", true}}));
  EXPECT_FALSE(camera_opencv::choose_device({}));
}

TEST(CameraUtils, ParsesFourcc) {
  const auto mjpg = camera_opencv::fourcc_code("MJPG");
  ASSERT_TRUE(mjpg);
  EXPECT_EQ(static_cast<unsigned>(*mjpg), static_cast<unsigned>(V4L2_PIX_FMT_MJPEG));
  EXPECT_EQ(camera_opencv::fourcc_text(*mjpg), "MJPG");
  EXPECT_EQ(static_cast<unsigned>(*camera_opencv::fourcc_code("YUYV")),
            static_cast<unsigned>(V4L2_PIX_FMT_YUYV));
  EXPECT_FALSE(camera_opencv::fourcc_code("MJP"));
  EXPECT_FALSE(camera_opencv::fourcc_code("MJPEG"));
  EXPECT_FALSE(camera_opencv::fourcc_code(std::string("MJ\nG")));
  EXPECT_EQ(camera_opencv::fourcc_text(0), "????");
}
