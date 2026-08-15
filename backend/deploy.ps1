param(
    [Parameter(Mandatory = $true)]
    [string]$StackName,

    [Parameter(Mandatory = $true)]
    [string]$Region,

    [Parameter(Mandatory = $true)]
    [string]$DatabaseUrl,

    [Parameter(Mandatory = $true)]
    [string]$GeminiApiKey,

    [string]$AllowedOrigins = "",
    [string]$ApiPrefix = "/api",
    [string]$DebugMode = "False",
    [string]$GeminiModel = "gemini-3.1-flash-lite",
    [string]$S3Bucket = ""
)

$ErrorActionPreference = "Stop"

$samBuildArgs = @("build", "--template-file", "template.yaml")
$samDeployArgs = @(
    "deploy",
    "--stack-name", $StackName,
    "--region", $Region,
    "--capabilities", "CAPABILITY_IAM",
    "--parameter-overrides",
    "GeminiApiKey=$GeminiApiKey",
    "DatabaseUrl=$DatabaseUrl",
    "AllowedOrigins=$AllowedOrigins",
    "ApiPrefix=$ApiPrefix",
    "DebugMode=$DebugMode",
    "GeminiModel=$GeminiModel"
)

if ($S3Bucket) {
    $samDeployArgs += @("--s3-bucket", $S3Bucket)
} else {
    $samDeployArgs += "--resolve-s3"
}

sam @samBuildArgs
sam @samDeployArgs
