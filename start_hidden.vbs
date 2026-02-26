Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "C:\_projects_\ghostgpt"
WshShell.Run """C:\Users\rohit\AppData\Roaming\Python\Python313\Scripts\ghostgpt.exe"" serve", 0, False
