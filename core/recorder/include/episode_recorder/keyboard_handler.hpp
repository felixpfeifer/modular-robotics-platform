#pragma once

#include <atomic>
#include <functional>
#include <thread>

namespace episode_recorder {

/// Non-blocking keyboard handler that reads stdin for single-key commands.
/// Runs in a background thread with raw terminal mode.
///
/// Key bindings:
///   SPACE / 's' -> start recording
///   'y'         -> mark success and finalize
///   'n'         -> mark failure and finalize
///   'a'         -> add an operator annotation
///   'q' / ESC   -> quit
enum class KeyCommand {
    kNone,
    kStart,
    kSuccess,
    kFailure,
    kAnnotate,
    kQuit,
};

class KeyboardHandler {
public:
    using Callback = std::function<void(KeyCommand)>;

    explicit KeyboardHandler(Callback callback);
    ~KeyboardHandler();

    /// Start listening (spawns thread).
    void start();

    /// Stop listening and join thread.
    void stop();

    /// For testing: inject a command without actual keyboard input.
    void inject_command(KeyCommand cmd);

private:
    Callback callback_;
    std::atomic<bool> running_{false};
    std::thread thread_;

    void listen_loop();
};

}  // namespace episode_recorder
