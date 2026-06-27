on run argv
    set cols to (item 1 of argv) as integer
    tell application "iTerm2"
        tell current session of current window
            set columns to cols
        end tell
    end tell
end run
