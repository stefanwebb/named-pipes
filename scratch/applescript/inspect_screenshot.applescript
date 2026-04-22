do shell script "open -a Screenshot"
delay 1

tell application "System Events"
    tell process "screencaptureui"
        repeat until (count of windows) > 0
            delay 0.1
        end repeat

        set w to window 1
        set output to "Window: " & (name of w) & linefeed
        set output to output & "Children:" & linefeed

        repeat with elem in (UI elements of w)
            set output to output & "  " & (class of elem as text)
            try
                set output to output & " title=" & (title of elem as text)
            end try
            try
                set output to output & " desc=" & (description of elem as text)
            end try
            try
                set output to output & " val=" & (value of elem as text)
            end try
            set output to output & linefeed
        end repeat

        return output
    end tell
end tell
