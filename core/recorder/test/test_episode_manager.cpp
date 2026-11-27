#include <gtest/gtest.h>

#include <filesystem>
#include <fstream>

#include "episode_recorder/episode_manager.hpp"

namespace fs = std::filesystem;

class EpisodeManagerTest : public ::testing::Test {
protected:
    void SetUp() override {
        test_dir_ = "/tmp/episode_recorder_test_" + std::to_string(getpid());
        fs::remove_all(test_dir_);
    }
    void TearDown() override { fs::remove_all(test_dir_); }

    const std::string kId1 = "123e4567-e89b-42d3-a456-426614174000";
    const std::string kId2 = "123e4567-e89b-42d3-a456-426614174001";
    std::string test_dir_;
};

TEST_F(EpisodeManagerTest, CreatesLayout) {
    episode_recorder::EpisodeManager manager(test_dir_);
    EXPECT_TRUE(fs::is_directory(test_dir_ + "/.staging"));
    EXPECT_TRUE(fs::is_directory(test_dir_ + "/episodes"));
}

TEST_F(EpisodeManagerTest, RejectsUnsafeIdentifier) {
    episode_recorder::EpisodeManager manager(test_dir_);
    EXPECT_THROW(manager.begin_episode("../ep_0"), std::invalid_argument);
}

TEST_F(EpisodeManagerTest, BeginsAndAtomicallyFinalizesEpisode) {
    episode_recorder::EpisodeManager manager(test_dir_);
    const auto staging = manager.begin_episode(kId1);
    std::ofstream(staging / "marker") << "raw";
    const auto final = manager.finalize_episode(kId1);
    EXPECT_FALSE(fs::exists(staging));
    EXPECT_TRUE(fs::exists(final / "marker"));
    ASSERT_EQ(manager.list_episodes().size(), 1u);
}

TEST_F(EpisodeManagerTest, RefusesDuplicateUuid) {
    episode_recorder::EpisodeManager manager(test_dir_);
    static_cast<void>(manager.begin_episode(kId1));
    EXPECT_THROW(manager.begin_episode(kId1), std::runtime_error);
    static_cast<void>(manager.finalize_episode(kId1));
    EXPECT_THROW(manager.begin_episode(kId1), std::runtime_error);
}

TEST_F(EpisodeManagerTest, DiscardsOnlyStagingArtifact) {
    episode_recorder::EpisodeManager manager(test_dir_);
    static_cast<void>(manager.begin_episode(kId1));
    EXPECT_TRUE(manager.discard_staging(kId1));
    EXPECT_FALSE(manager.discard_staging(kId1));
}

TEST_F(EpisodeManagerTest, ListsUuidDirectoriesSorted) {
    episode_recorder::EpisodeManager manager(test_dir_);
    static_cast<void>(manager.begin_episode(kId2));
    static_cast<void>(manager.finalize_episode(kId2));
    static_cast<void>(manager.begin_episode(kId1));
    static_cast<void>(manager.finalize_episode(kId1));
    const auto episodes = manager.list_episodes();
    ASSERT_EQ(episodes.size(), 2u);
    EXPECT_EQ(episodes[0].filename(), kId1);
    EXPECT_EQ(episodes[1].filename(), kId2);
}
