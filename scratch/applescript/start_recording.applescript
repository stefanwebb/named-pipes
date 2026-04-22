tell application "System Events"
    do shell script "open -a Screenshot"
    delay 1
    tell process "Screenshot"
        click checkbox "Record Entire Screen" of window 1
        delay 0.5 
        click button "Record" of window 1
    end tell
end tell