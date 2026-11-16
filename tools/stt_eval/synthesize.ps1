param([Parameter(Mandatory=$true)][string]$Corpus, [Parameter(Mandatory=$true)][string]$OutputDirectory)
$ErrorActionPreference = 'Stop'
# Local synthetic speech only. Never accepts captured Live audio.
$speaker = New-Object -ComObject SAPI.SpVoice
$voices = $speaker.GetVoices()
$items = Get-Content -LiteralPath $Corpus -Raw -Encoding UTF8 | ConvertFrom-Json
foreach ($item in $items) {
    if ($item.fixture) { continue }
    $name = if ($item.language -eq 'en') { 'Microsoft Zira Desktop' } else { 'Microsoft Sabina Desktop' }
    $selected = $null
    foreach ($voice in $voices) { if ($voice.GetDescription().StartsWith($name)) { $selected = $voice; break } }
    if ($null -eq $selected) { throw "Required local voice unavailable: $name" }
    $speaker.Voice = $selected
    $speaker.Rate = 0
    $stream = New-Object -ComObject SAPI.SpFileStream
    # SpeechAudioFormatType SAFT16kHz16BitMono = 18.
    $stream.Format.Type = 18
    $path = Join-Path $OutputDirectory ($item.id + '.wav')
    $stream.Open($path, 3, $false)
    try { $speaker.AudioOutputStream = $stream; [void]$speaker.Speak($item.text) }
    finally { $stream.Close() }
}
