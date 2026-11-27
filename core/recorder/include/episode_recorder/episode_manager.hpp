#pragma once

#include <filesystem>
#include <string>
#include <vector>

namespace episode_recorder {

/// Owns the crash-safe, UUID-addressed raw episode directory layout.
class EpisodeManager {
public:
    explicit EpisodeManager(const std::string& dataset_dir);

    [[nodiscard]] std::string dataset_dir() const;
    [[nodiscard]] std::filesystem::path staging_path(const std::string& episode_id) const;
    [[nodiscard]] std::filesystem::path episode_path(const std::string& episode_id) const;
    [[nodiscard]] std::filesystem::path begin_episode(const std::string& episode_id);
    [[nodiscard]] std::filesystem::path finalize_episode(const std::string& episode_id);
    bool discard_staging(const std::string& episode_id);
    [[nodiscard]] std::vector<std::filesystem::path> list_episodes() const;
    [[nodiscard]] std::vector<std::filesystem::path> list_staging() const;

private:
    std::filesystem::path dataset_dir_;
    std::filesystem::path staging_dir_;
    std::filesystem::path episodes_dir_;

    static void validate_episode_id(const std::string& episode_id);
};

}  // namespace episode_recorder
