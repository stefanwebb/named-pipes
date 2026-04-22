tell application "System Events"                                                        
      tell process "screencaptureui"
          -- Stop button lives in the menu bar status extras (menu bar 2)                 
          click (first menu bar item of menu bar 2 whose description contains "Stop")
      end tell                                                                            
end tell  