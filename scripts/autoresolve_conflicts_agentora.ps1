param(
  [string]$BaseBranch = 'main'
)

Write-Host '[1/6] merge base into current branch'
git merge "origin/$BaseBranch" 2>$null

Write-Host '[2/6] prefer ours for app code if conflicts exist'
git checkout --ours -- server/app
if ($LASTEXITCODE -ne 0) { }
git checkout --ours -- server/tests
if ($LASTEXITCODE -ne 0) { }
git checkout --ours -- web/src
if ($LASTEXITCODE -ne 0) { }
git checkout --ours -- web/index.html
if ($LASTEXITCODE -ne 0) { }
git checkout --ours -- scripts/make_release_zip.py
if ($LASTEXITCODE -ne 0) { }
git checkout --ours -- server/requirements.txt
if ($LASTEXITCODE -ne 0) { }

Write-Host '[3/6] ensure no conflict markers'
rg -n "<{7}|={7}|>{7}" .
if ($LASTEXITCODE -eq 0) { throw 'Conflict markers found; resolve manually.' }

Write-Host '[4/6] commit resolution'
git add -A
git commit -m "chore: resolve PR conflicts and sync with main"

Write-Host '[5/6] run checks'
python -m pip install -r server/requirements.txt
python -m compileall server/app
$env:AGENTORA_USE_MOCK_OLLAMA = 'true'
pytest server/tests
Push-Location web
npm ci
if ($LASTEXITCODE -ne 0) {
  npm install
  npm ci
}
npm run build
Pop-Location

Write-Host '[6/6] push'
git push -u origin HEAD
