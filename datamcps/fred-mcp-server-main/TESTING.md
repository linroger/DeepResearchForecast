# Testing Strategy for FRED MCP Server

This document outlines the testing strategy for the `FRED MCP Server` project.

## Test Coverage

The project aims for comprehensive yet meaningful test coverage, including:
- Unit tests for individual modules
- Integration tests for the complete server

## Test Structure

Tests are organized as follows:
- `test/unit/` - Unit tests for individual modules
- `test/integration/` - Integration tests for the complete server

## Test Files

The following test files have been created:

1. `test/unit/fred/registry.test.ts` - Tests for the FRED series registry
2. `test/unit/fred/client.test.ts` - Tests for the FRED API client
3. `test/unit/fred/tools.test.ts` - Tests for MCP tool registration
4. `test/unit/common/request.test.ts` - Tests for the request utilities
5. `test/unit/index.test.ts` - Tests for the main server module
6. `test/integration/server.test.ts` - Integration tests for the server

## Known Issues

1. Jest configuration with ESM modules is complex and requires careful setup
2. Using named imports with jest.mock() is challenging in ESM context
3. In ESM modules, imports are read-only and cannot be directly overridden for mocking
4. Index module immediately executes server startup code, making it difficult to test

## Running Tests

```bash
# Run all tests
pnpm test

# Run specific test
pnpm test:registry
pnpm test:client
```

## Test Dependencies

- `Jest` for test runner
- `ts-jest` for TypeScript support
