while ($true) {
    try {
        & py "C:\Users\DavidSherize_dd1jhqb\Downloads\GC\v2\py\fix_sugya_step_bounds.py" 2>&1 | Out-Null
        & py "C:\Users\DavidSherize_dd1jhqb\Downloads\GC\v2\py\postprocess_overviews.py" 2>&1 | Out-Null
        & py "C:\Users\DavidSherize_dd1jhqb\Downloads\GC\v2\py\update_index.py" 2>&1 | Out-Null
    } catch {}
    Start-Sleep 90
}
