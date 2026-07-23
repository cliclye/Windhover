; NSIS hooks for Windhover (Tauri).
; The desktop app keeps windhover-server.exe / windhover-engine.exe running as
; sidecars. NSIS cannot overwrite those locked files on upgrade unless we stop
; them first — otherwise users see:
;   "Error opening file for writing: ...\windhover-server.exe"

!macro _WindhoverKillProcesses
  DetailPrint "Stopping Windhover processes so files can be updated..."
  ; /T kills the process tree (main app + spawned sidecars).
  nsExec::ExecToLog 'taskkill /F /T /IM Windhover.exe'
  Pop $0
  nsExec::ExecToLog 'taskkill /F /T /IM windhover.exe'
  Pop $0
  nsExec::ExecToLog 'taskkill /F /T /IM windhover-server.exe'
  Pop $0
  nsExec::ExecToLog 'taskkill /F /T /IM windhover-engine.exe'
  Pop $0
  Sleep 2000
!macroend

!macro NSIS_HOOK_PREINSTALL
  !insertmacro _WindhoverKillProcesses
  ; Best-effort remove old sidecars before copy (ignore failures).
  Delete /REBOOTOK "$INSTDIR\windhover-server.exe"
  Delete /REBOOTOK "$INSTDIR\windhover-engine.exe"
  ClearErrors
!macroend

!macro NSIS_HOOK_PREUNINSTALL
  !insertmacro _WindhoverKillProcesses
!macroend
