#include "episode_recorder/keyboard_handler.hpp"

#include <poll.h>
#include <termios.h>
#include <unistd.h>

#include <iostream>

namespace episode_recorder {

KeyboardHandler::KeyboardHandler(Callback callback)
    : callback_(std::move(callback)) {}

KeyboardHandler::~KeyboardHandler() {
    stop();
}

void KeyboardHandler::start() {
    if (running_.exchange(true)) {
        return;  // Already running
    }
    thread_ = std::thread(&KeyboardHandler::listen_loop, this);
}

void KeyboardHandler::stop() {
    running_ = false;
    if (thread_.joinable()) {
        thread_.join();
    }
}

void KeyboardHandler::inject_command(KeyCommand cmd) {
    if (callback_) {
        callback_(cmd);
    }
}

void KeyboardHandler::listen_loop() {
    // Set terminal to raw mode
    struct termios old_settings{};
    struct termios new_settings{};
    tcgetattr(STDIN_FILENO, &old_settings);
    new_settings = old_settings;
    new_settings.c_lflag &= ~(ICANON | ECHO);
    new_settings.c_cc[VMIN] = 0;
    new_settings.c_cc[VTIME] = 1;  // 100ms timeout
    tcsetattr(STDIN_FILENO, TCSANOW, &new_settings);

    while (running_) {
        pollfd descriptor{STDIN_FILENO, POLLIN, 0};
        const int ready = poll(&descriptor, 1, 100);
        if (ready <= 0 || !(descriptor.revents & POLLIN)) {
            continue;
        }
        char c = 0;
        ssize_t n = read(STDIN_FILENO, &c, 1);
        if (n <= 0) {
            continue;
        }

        KeyCommand cmd = KeyCommand::kNone;
        switch (c) {
            case ' ':
            case 's':
            case 'S':
                cmd = KeyCommand::kStart;
                break;
            case 'y':
            case 'Y':
                cmd = KeyCommand::kSuccess;
                break;
            case 'n':
            case 'N':
                cmd = KeyCommand::kFailure;
                break;
            case 'a':
            case 'A':
                cmd = KeyCommand::kAnnotate;
                break;
            case 'q':
            case 'Q':
            case 27:  // ESC
                cmd = KeyCommand::kQuit;
                break;
            default:
                break;
        }

        if (cmd != KeyCommand::kNone && callback_) {
            callback_(cmd);
        }
    }

    // Restore terminal settings
    tcsetattr(STDIN_FILENO, TCSANOW, &old_settings);
}

}  // namespace episode_recorder
