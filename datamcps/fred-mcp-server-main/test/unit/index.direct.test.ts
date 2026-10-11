import { describe, expect, test, jest, beforeEach, afterEach } from '@jest/globals';
import * as indexModule from '../../src/index.js';
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";

// This is a special test file that directly tests the index.ts module
// including its main function and error handling
describe('Index module direct tests', () => {
  // Save original implementation
  const originalProcessExit = process.exit;
  const originalProcessOn = process.on;
  const originalConsoleError = console.error;
  
  beforeEach(() => {
    // Mock console.error
    console.error = jest.fn();
    
    // Mock process.exit
    process.exit = jest.fn() as any;
    
    // Mock process.on
    process.on = jest.fn(() => process) as any;
  });
  
  afterEach(() => {
    // Restore original implementations
    process.exit = originalProcessExit;
    process.on = originalProcessOn;
    console.error = originalConsoleError;
    
    // Clear mocks
    jest.clearAllMocks();
  });
  
  test('createServer returns a properly initialized server', () => {
    // Call the function
    const server = indexModule.createServer();
    
    // Verify it's an object with expected properties
    expect(server).toBeDefined();
    expect(typeof server).toBe('object');
  });
  
  test('startServer connects and sets up SIGINT handler', async () => {
    // Create mock objects
    const mockConnect = jest.fn().mockResolvedValue(undefined);
    const mockServer = { connect: mockConnect };
    const mockTransport = {};
    
    // Call startServer
    const result = await indexModule.startServer(
      mockServer as unknown as McpServer,
      mockTransport as unknown as StdioServerTransport
    );
    
    // Verify connection was established
    expect(mockConnect).toHaveBeenCalledWith(mockTransport);
    
    // Verify SIGINT handler was set up
    expect(process.on).toHaveBeenCalledWith('SIGINT', expect.any(Function));
    
    // Verify success result
    expect(result).toBe(true);
    
    // Verify console logs
    expect(console.error).toHaveBeenCalledWith(expect.stringContaining('FRED MCP Server starting...'));
    expect(console.error).toHaveBeenCalledWith(expect.stringContaining('FRED MCP Server running on stdio'));
  });
  
  test('startServer handles connection error', async () => {
    // Create mock server that throws on connect
    const mockError = new Error('Connection failed');
    const mockServer = {
      connect: jest.fn().mockRejectedValue(mockError)
    };
    const mockTransport = {};
    
    // Call startServer
    const result = await indexModule.startServer(
      mockServer as unknown as McpServer,
      mockTransport as unknown as StdioServerTransport
    );
    
    // Verify error handling
    expect(result).toBe(false);
    expect(console.error).toHaveBeenCalledWith(expect.stringContaining('Failed to start server:'), mockError);
  });
  
  test('SIGINT handler calls process.exit', async () => {
    // Create mock server
    const mockServer = {
      connect: jest.fn().mockResolvedValue(undefined)
    };
    const mockTransport = {};
    
    // Capture the SIGINT handler
    await indexModule.startServer(
      mockServer as unknown as McpServer,
      mockTransport as unknown as StdioServerTransport
    );
    
    // Get the handler function
    const sigintHandler = (process.on as jest.Mock).mock.calls.find(
      call => call[0] === 'SIGINT'
    )[1];
    
    // Verify handler is a function
    expect(typeof sigintHandler).toBe('function');
    
    // Call the handler
    sigintHandler();
    
    // Verify process.exit was called
    expect(console.error).toHaveBeenCalledWith(expect.stringContaining('shutting down'));
    expect(process.exit).toHaveBeenCalledWith(0);
  });
});