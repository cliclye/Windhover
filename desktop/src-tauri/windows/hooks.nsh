; NSIS hooks for Windhover (Tauri).
; The desktop app keeps windhover-server.exe / windhover-engine.exe running as
; sidecars. NSIS cannot overwrite those locked files on upgrade unless we stop
; them first — otherwise users see:
;   "Error opening file for writing: ...\windhover-server.exe"

!include "LogicLib.nsh"
!include "nsDialogs.nsh"

!macro _WindhoverKillProcesses
  DetailPrint "Stopping Windhover processes (so files can be updated)..."
  ; /T kills the process tree (main app + spawned sidecars).
  nsExec::ExecToLog 'taskkill /F /T /IM Windhover.exe'
  Pop $0
  nsExec::ExecToLog 'taskkill /F /T /IM windhover-server.exe'
  Pop $0
  nsExec::ExecToLog 'taskkill /F /T /IM windhover-engine.exe'
  Pop $0
  ; Also match legacy / lowercase names if present.
  nsExec::ExecToLog 'taskkill /F /T /IM windhover.exe'
  Pop $0
  Sleep 1500
!macroend

!macro NSIS_HOOK_PREINSTALL
  !insertmacro _WindhoverKillProcesses
  ; Best-effort delete of locked sidecar binaries before copy.
  ${If} ${FileExists} "$INSTDIR\windhover-server.exe"
    ClearErrors
    Delete "$INSTDIR\windhover-server.exe"
    ${If} ${Errors}
      DetailPrint "Retrying delete of windhover-server.exe..."
      Sleep 1000
      nsExec::ExecToLog 'taskkill /F /T /IM windhover-server.exe'
      Pop $0
      Sleep 1000
      ClearErrors
      Delete "$INSTDIR\windhover-server.exe"
    ${EndIf}
  ${EndIf}
  ${If} ${FileExists} "$INSTDIR\windhover-engine.exe"
    ClearErrors
    Delete "$INSTDIR\windhover-engine.exe"
    ${If} ${Errors}
      DetailPrint "Retrying delete of windhover-engine.exe..."
      Sleep 1000
      nsExec::ExecToLog 'taskkill /F /T /IM windhover-engine.exe'
      Pop $0
      Sleep 1000
      ClearErrors
      Delete "$INSTDIR\windhover-engine.exe"
    ${EndIf}
  ${EndIf}
!macroend

!macro NSIS_HOOK_PREUNINSTALL
  !insertmacro _WindhoverKillProcesses
!macroend
