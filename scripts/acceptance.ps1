# Walks the three acceptance steps against a running stack.
#
#   1. sign in as a@test.com, add tickers, dismiss the critical card
#   2. sign out, sign in as b@test.com -> empty watchlist, no shared state
#   3. sign out, sign in as a@test.com -> tickers still there, still dismissed
#
# The same claim is asserted without a browser in
# tests/test_auth.py::test_two_users_watchlists_and_snapshots_are_fully_isolated.
#
#   docker compose up -d --build
#   powershell -File scripts/acceptance.ps1

$ErrorActionPreference = "Stop"
$api = "http://localhost:8000"

function Login($email) {
    $r = Invoke-RestMethod -Method Post -Uri "$api/api/auth/login" `
        -ContentType 'application/json' -Body (@{ email = $email } | ConvertTo-Json)
    return @{
        headers = @{ Authorization = "Bearer $($r.access_token)" }
        email   = $r.email
        id      = $r.user_id
    }
}

function Tickers($who) {
    $items = Invoke-RestMethod -Uri "$api/api/watchlist" -Headers $who.headers
    if ($null -eq $items) { return @() }
    return @($items | ForEach-Object { $_.ticker })
}

Write-Host "`n--- step 1: sign in as a@test.com ---------------------------------"

# A brand-new ticker is checkpointed at the moment you add it, so it is quiet by
# construction. Seeding A with a checkpoint some sessions back is what puts a
# real diff -- and therefore a critical card -- on screen. How far back that has
# to be depends on where the replay clock currently is, so widen until one
# appears rather than guessing a fixed number.
$A = $null
$digest = $null
foreach ($back in 3, 5, 8, 13, 21) {
    docker compose exec -T postgres psql -U smw -d smw -q -c `
        "DELETE FROM app_users WHERE email IN ('a@test.com','b@test.com');"
    docker compose exec -T -e LOG_LEVEL=WARNING api python -m scripts.seed_demo `
        --email a@test.com --tickers NFLX,META,AAPL --back-sessions $back | Out-Null

    $A = Login 'a@test.com'
    foreach ($t in 'MSFT', 'NVDA') {
        Invoke-RestMethod -Method Post -Uri "$api/api/watchlist" -Headers $A.headers `
            -ContentType 'application/json' -Body (@{ ticker = $t } | ConvertTo-Json) | Out-Null
    }
    $digest = Invoke-RestMethod -Uri "$api/api/digest" -Headers $A.headers
    Write-Host ("  last seen {0} sessions back -> {1} critical, {2} notable, {3} quiet" -f `
            $back, $digest.counts.critical, $digest.counts.notable, $digest.counts.quiet)
    if ($digest.counts.critical -gt 0) { break }
}

Write-Host "signed in as $($A.email)"
Write-Host "A watchlist: $((Tickers $A) -join ', ')"

$loud = @($digest.cards | Where-Object { $_.tier -eq 'critical' })
if ($loud.Count -eq 0) {
    Write-Host "no critical surfaced at any depth; dismissing the loudest card instead" -ForegroundColor Yellow
    $loud = @($digest.cards | Select-Object -First 1)
}
$target = $loud[0].ticker
$ack = Invoke-RestMethod -Method Post -Uri "$api/api/ack" -Headers $A.headers `
    -ContentType 'application/json' `
    -Body (@{ token = $digest.token; tickers = @($target) } | ConvertTo-Json)
Write-Host "dismissed $target -> $($ack.results.$target)"

Write-Host "`n--- step 2: sign out, sign in as b@test.com -----------------------"
$B = Login 'b@test.com'
$bList = Tickers $B
$bDigest = Invoke-RestMethod -Uri "$api/api/digest" -Headers $B.headers
Write-Host "B watchlist: $(if ($bList.Count) { $bList -join ', ' } else { '(empty)' })"
Write-Host "B digest:    $($bDigest.counts.total) tickers"

Write-Host "`n--- step 3: sign out, sign back in as a@test.com ------------------"
$A2 = Login 'a@test.com'
$aList = Tickers $A2
$aDigest = Invoke-RestMethod -Uri "$api/api/digest" -Headers $A2.headers
Write-Host "A watchlist: $($aList -join ', ')"
Write-Host "A digest:    $($aDigest.counts.critical) critical"

Write-Host "`n--- result --------------------------------------------------------"
$checks = @(
    @{ name = "A and B are different users"; pass = $A.id -ne $B.id }
    @{ name = "B's watchlist is empty"; pass = $bList.Count -eq 0 }
    @{ name = "B's digest is empty"; pass = $bDigest.counts.total -eq 0 }
    @{ name = "A's tickers survived the round trip"; pass = $aList.Count -eq 5 }
    @{ name = "A's dismissal persisted"; pass = $aDigest.counts.critical -eq 0 }
)
foreach ($c in $checks) {
    $mark = if ($c.pass) { "PASS" } else { "FAIL" }
    $colour = if ($c.pass) { "Green" } else { "Red" }
    Write-Host ("{0}  {1}" -f $mark, $c.name) -ForegroundColor $colour
}
$failed = @($checks | Where-Object { -not $_.pass }).Count
Write-Host "`n$($checks.Count - $failed)/$($checks.Count) checks passed`n"
exit $failed
