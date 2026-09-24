Set sh = CreateObject("WScript.Shell")
' Hidden panic sell-all (simulate by default — safe). Change args only if you intend to send.
repo = "C:\Users\jpana\Documents\HermesTools\trenchnet"
py = repo & "\.venv\Scripts\python.exe"
cmd = """" & py & """ -u -m trenchnet.cli sell-all"
sh.CurrentDirectory = repo
rc = sh.Run(cmd, 0, True)
If rc = 0 Then
  MsgBox "TRENCHNET sell-all finished (simulate/default). Check data\live\trades.jsonl and /live.", 64, "TRENCHNET SELL-ALL"
Else
  MsgBox "TRENCHNET sell-all exited with code " & rc & ". See runbook.", 16, "TRENCHNET SELL-ALL"
End If
