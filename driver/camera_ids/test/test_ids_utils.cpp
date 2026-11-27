#include <camera_ids/ids_utils.hpp>

#include <gtest/gtest.h>

#include <string>
#include <vector>

using camera_ids::CameraEntry;
using camera_ids::select_camera;

namespace {
std::vector<CameraEntry> cameras() {
  return {
      {"4102000001", "UI-1240LE-C", 1, 1, true},
      {"4102000002", "UI-1240LE-C", 1, 2, false},
      {"4103000003", "UI-5240CP-M", 7, 3, false},
  };
}
} // namespace

TEST(IdsUtils, AutomaticSelectionSkipsCamerasInUse) {
  std::string error;
  EXPECT_EQ(select_camera(cameras(), "", 0, error), 1);
}

TEST(IdsUtils, SelectsBySerialFirst) {
  std::string error;
  EXPECT_EQ(select_camera(cameras(), "4103000003", 1, error), 2);
}

TEST(IdsUtils, SelectsByCameraId) {
  std::string error;
  EXPECT_EQ(select_camera(cameras(), "", 7, error), 2);
  // Several cameras share the default ID 1: the first free one wins.
  EXPECT_EQ(select_camera(cameras(), "", 1, error), -1);
  EXPECT_NE(error.find("in use"), std::string::npos);
}

TEST(IdsUtils, ExplicitCameraInUseIsAnError) {
  std::string error;
  EXPECT_EQ(select_camera(cameras(), "4102000001", 0, error), -1);
  EXPECT_NE(error.find("in use"), std::string::npos);
}

TEST(IdsUtils, ReportsMissingCameras) {
  std::string error;
  EXPECT_EQ(select_camera({}, "", 0, error), -1);
  EXPECT_NE(error.find("no IDS"), std::string::npos);
  EXPECT_EQ(select_camera(cameras(), "999", 0, error), -1);
  EXPECT_NE(error.find("999"), std::string::npos);
  EXPECT_EQ(select_camera(cameras(), "", 42, error), -1);
  EXPECT_NE(error.find("42"), std::string::npos);
}

TEST(IdsUtils, ConvertsAsciiParameterFilePath) {
  std::wstring wide;
  ASSERT_TRUE(camera_ids::ascii_to_wide("/config/camera.ini", wide));
  EXPECT_EQ(wide, L"/config/camera.ini");
  EXPECT_FALSE(camera_ids::ascii_to_wide("/config/kamera-\xc3\xa4.ini", wide));
}
