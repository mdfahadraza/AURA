Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "D:\AURA\AURA"

' Start server hidden
WshShell.Run """D:\AURA\AURA\.venv\Scripts\python.exe"" server.py", 0, False

' Small delay for server startup
WScript.Sleep 2000

' Launch GUI (visible, wait for it to close)
WshShell.Run """D:\AURA\AURA\.venv\Scripts\python.exe"" roadmap_gui.py", 1, True

' Kill server when GUI closes
WshShell.Run "taskkill /F /IM python.exe /FI ""WINDOWTITLE eq AURA""", 0, False
