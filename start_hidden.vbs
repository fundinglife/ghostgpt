Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "C:\_projects_\customgpts"
WshShell.Run """C:\Users\rohit\AppData\Roaming\Python\Python313\Scripts\customgpts.exe"" serve", 0, False
