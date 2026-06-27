tell application "iTerm2"
    set b to bounds of current window
    set w to (item 3 of b) - (item 1 of b)
    set h to (item 4 of b) - (item 2 of b)
    set ratio to round ((w / h) * 100) rounding as taught in school
    set ratio to ratio / 100
    return "width: " & w & ", height: " & h & ", aspect ratio: " & ratio
end tell
