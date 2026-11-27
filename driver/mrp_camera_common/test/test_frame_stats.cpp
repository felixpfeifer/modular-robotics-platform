#include <mrp_camera_common/frame_stats.hpp>

#include <gtest/gtest.h>

using mrp_camera_common::FrameStats;
using mrp_camera_common::StallWatchdog;
using mrp_camera_common::SteadyClock;
using namespace std::chrono_literals;

TEST(FrameStats, ReportsOncePerPeriodAndResets) {
  const auto t0 = SteadyClock::time_point(100s);
  FrameStats stats(5s, t0);
  for (int i = 0; i < 150; ++i) {
    stats.add_frame(std::size_t{40} * 1024);
  }
  stats.add_drop();
  EXPECT_FALSE(stats.poll(t0 + 4s));

  const auto report = stats.poll(t0 + 5s);
  ASSERT_TRUE(report);
  EXPECT_DOUBLE_EQ(report->seconds, 5.0);
  EXPECT_EQ(report->frames, 150U);
  EXPECT_EQ(report->dropped, 1U);
  EXPECT_DOUBLE_EQ(report->fps(), 30.0);
  EXPECT_EQ(report->average_kib(), 40U);
  EXPECT_NEAR(report->mbit_per_second(), 150.0 * 40 * 1024 * 8 / 5e6, 1e-9);

  EXPECT_FALSE(stats.poll(t0 + 6s)); // a new window started at t0 + 5 s
  const auto next = stats.poll(t0 + 10s);
  ASSERT_TRUE(next);
  EXPECT_EQ(next->frames, 0U);
  EXPECT_EQ(next->average_kib(), 0U);
}

TEST(FrameStats, EmptyReportHasZeroRates) {
  const mrp_camera_common::StatsReport report;
  EXPECT_EQ(report.fps(), 0.0);
  EXPECT_EQ(report.mbit_per_second(), 0.0);
  EXPECT_FALSE(mrp_camera_common::format_report(report).empty());
}

TEST(StallWatchdog, StallsOnlyAfterSilence) {
  const auto t0 = SteadyClock::time_point(50s);
  StallWatchdog watchdog(10s, t0);
  EXPECT_FALSE(watchdog.stalled(t0 + 9s));
  EXPECT_TRUE(watchdog.stalled(t0 + 10s));
  watchdog.feed(t0 + 9s);
  EXPECT_FALSE(watchdog.stalled(t0 + 18s));
  EXPECT_EQ(watchdog.silence(t0 + 18s), 9s);
  EXPECT_TRUE(watchdog.stalled(t0 + 19s));
}
