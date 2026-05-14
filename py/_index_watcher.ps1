$root = Split-Path -Parent $MyInvocation.MyCommand.Path
while ($true) {
    try {
        & py "$root\fix_sugya_step_bounds.py" 2>&1 | Out-Null
        & py "$root\postprocess_overviews.py" 2>&1 | Out-Null
        & py "$root\update_index.py" 2>&1 | Out-Null
    } catch {}
    Start-Sleep 90
}
