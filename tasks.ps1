# tasks.ps1 — dev task runner
# Usage: .\tasks.ps1 <task>
# Tasks: test, test-pipeline, test-api, test-adapters, test-stores, dev, smoke, build-test
param([string]$task = "test")

Set-Location $PSScriptRoot

switch ($task) {

    "test" {
        docker compose run --rm test
    }

    "test-pipeline" {
        docker compose run --rm test pytest tests/pipeline -q -m "not integration"
    }

    "test-api" {
        docker compose run --rm test pytest tests/api tests/general -q -m "not integration"
    }

    "test-adapters" {
        docker compose run --rm test pytest tests/adapters -q -m "not integration"
    }

    "test-stores" {
        docker compose run --rm test pytest tests/stores -q -m "not integration"
    }

    "test-retrieval" {
        docker compose run --rm test pytest tests/retrieval -q -m "not integration"
    }

    "build-test" {
        docker compose build test
    }

    "dev" {
        # Start API in mock mode — no Qdrant, no Postgres, no S3
        $env:AI_PROVIDER = "mock"
        $env:VECTOR_STORE = "memory"
        $env:METADATA_STORE = "memory"
        $env:USE_S3 = "false"
        uvicorn api.main:app --reload --port 8000
    }

    "smoke" {
        # Run one file through the full pipeline without any infra
        $script = @'
from adapters.file_adapter import FileAdapter
from pipeline.run import run
from utils.ai_provider import MockAIProvider
from utils.stores import InMemoryMetadataStore, InMemoryVectorStore

job = FileAdapter().map("data/sample/policy.txt", doc_id="smoke")
result = run(job, MockAIProvider(), InMemoryVectorStore(), InMemoryMetadataStore())
print(result)
'@
        docker compose run --rm -e AI_PROVIDER=mock -e VECTOR_STORE=memory -e METADATA_STORE=memory test `
            python -c $script
    }

    default {
        Write-Host "Available tasks:"
        Write-Host "  test            Run full test suite (Docker)"
        Write-Host "  test-pipeline   Run only pipeline tests"
        Write-Host "  test-api        Run only API + workflow tests"
        Write-Host "  test-adapters   Run only adapter tests"
        Write-Host "  test-stores     Run only store tests"
        Write-Host "  test-retrieval  Run only retrieval tests"
        Write-Host "  build-test      Rebuild the test Docker image"
        Write-Host "  dev             Start API locally in mock mode (no infra)"
        Write-Host "  smoke           Run one file through full pipeline (Docker, no infra)"
    }
}
