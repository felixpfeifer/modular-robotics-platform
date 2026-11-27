#include "episode_recorder/episode_manager.hpp"

#include <algorithm>
#include <regex>
#include <stdexcept>

namespace fs = std::filesystem;

namespace episode_recorder {

EpisodeManager::EpisodeManager(const std::string& dataset_dir)
    : dataset_dir_(dataset_dir), staging_dir_(dataset_dir_ / ".staging"),
      episodes_dir_(dataset_dir_ / "episodes") {
    fs::create_directories(staging_dir_);
    fs::create_directories(episodes_dir_);
}

std::string EpisodeManager::dataset_dir() const { return dataset_dir_.string(); }

void EpisodeManager::validate_episode_id(const std::string& episode_id) {
    static const std::regex uuid(
        "^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
        std::regex::icase);
    if (!std::regex_match(episode_id, uuid)) {
        throw std::invalid_argument("episode_id must be a canonical UUID");
    }
}

fs::path EpisodeManager::staging_path(const std::string& episode_id) const {
    validate_episode_id(episode_id);
    return staging_dir_ / episode_id;
}

fs::path EpisodeManager::episode_path(const std::string& episode_id) const {
    validate_episode_id(episode_id);
    return episodes_dir_ / episode_id;
}

fs::path EpisodeManager::begin_episode(const std::string& episode_id) {
    const auto staging = staging_path(episode_id);
    const auto final = episode_path(episode_id);
    if (fs::exists(staging) || fs::exists(final)) {
        throw std::runtime_error("episode UUID already exists: " + episode_id);
    }
    if (!fs::create_directory(staging)) {
        throw std::runtime_error("failed to create staging directory: " + staging.string());
    }
    return staging;
}

fs::path EpisodeManager::finalize_episode(const std::string& episode_id) {
    const auto staging = staging_path(episode_id);
    const auto final = episode_path(episode_id);
    if (!fs::exists(staging) || fs::exists(final)) {
        throw std::runtime_error("cannot finalize episode: " + episode_id);
    }
    fs::rename(staging, final);
    return final;
}

bool EpisodeManager::discard_staging(const std::string& episode_id) {
    const auto path = staging_path(episode_id);
    return fs::exists(path) && fs::remove_all(path) > 0;
}

std::vector<fs::path> EpisodeManager::list_episodes() const {
    std::vector<fs::path> result;
    for (const auto& entry : fs::directory_iterator(episodes_dir_)) {
        if (entry.is_directory()) result.push_back(entry.path());
    }
    std::sort(result.begin(), result.end());
    return result;
}

std::vector<fs::path> EpisodeManager::list_staging() const {
    std::vector<fs::path> result;
    for (const auto& entry : fs::directory_iterator(staging_dir_)) {
        if (entry.is_directory()) result.push_back(entry.path());
    }
    std::sort(result.begin(), result.end());
    return result;
}

}  // namespace episode_recorder
