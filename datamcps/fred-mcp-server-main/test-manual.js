#!/usr/bin/env node

/**
 * Manual testing script for FRED MCP Server tools
 */

import { createServer } from './build/index.js';

// Create a mock transport for testing
class TestTransport {
  async start() {}
  async send(message) {
    console.log('Response:', JSON.stringify(message, null, 2));
  }
}

async function testTools() {
  console.log('🧪 Testing FRED MCP Server Tools\n');
  
  const server = createServer();
  const transport = new TestTransport();
  
  // Connect the server
  await server.connect(transport);
  
  console.log('📋 Available tools:');
  const tools = server._tools;
  for (const [name, tool] of tools) {
    console.log(`  - ${name}`);
  }
  console.log('');
  
  // Test 1: Browse categories
  console.log('Test 1: Browse top-level categories');
  console.log('=====================================');
  try {
    const browseHandler = tools.get('fred_browse').handler;
    const result = await browseHandler({ 
      browse_type: 'categories',
      limit: 5 
    });
    console.log('✅ Categories:', JSON.parse(result.content[0].text));
  } catch (error) {
    console.error('❌ Error:', error.message);
  }
  console.log('');
  
  // Test 2: Search for GDP series
  console.log('Test 2: Search for GDP series');
  console.log('==============================');
  try {
    const searchHandler = tools.get('fred_search').handler;
    const result = await searchHandler({ 
      search_text: 'gross domestic product',
      limit: 3 
    });
    console.log('✅ Search results:', JSON.parse(result.content[0].text));
  } catch (error) {
    console.error('❌ Error:', error.message);
  }
  console.log('');
  
  // Test 3: Get GDP data
  console.log('Test 3: Get GDP data for 2023');
  console.log('==============================');
  try {
    const seriesHandler = tools.get('fred_get_series').handler;
    const result = await seriesHandler({ 
      series_id: 'GDP',
      observation_start: '2023-01-01',
      observation_end: '2023-12-31'
    });
    const data = JSON.parse(result.content[0].text);
    console.log('✅ GDP Data:');
    console.log(`  Series: ${data.title}`);
    console.log(`  Units: ${data.units}`);
    console.log(`  Observations: ${data.total_observations}`);
    if (data.data && data.data.length > 0) {
      console.log('  Latest values:');
      data.data.forEach(obs => {
        console.log(`    ${obs.date}: ${obs.value}`);
      });
    }
  } catch (error) {
    console.error('❌ Error:', error.message);
  }
  console.log('');
  
  // Test 4: Browse releases
  console.log('Test 4: Browse data releases');
  console.log('=============================');
  try {
    const browseHandler = tools.get('fred_browse').handler;
    const result = await browseHandler({ 
      browse_type: 'releases',
      limit: 5 
    });
    console.log('✅ Releases:', JSON.parse(result.content[0].text));
  } catch (error) {
    console.error('❌ Error:', error.message);
  }
  console.log('');
  
  // Test 5: Get unemployment rate with percent change
  console.log('Test 5: Get unemployment rate with transformations');
  console.log('===================================================');
  try {
    const seriesHandler = tools.get('fred_get_series').handler;
    const result = await seriesHandler({ 
      series_id: 'UNRATE',
      observation_start: '2024-01-01',
      units: 'pch',  // Percent change
      limit: 12
    });
    const data = JSON.parse(result.content[0].text);
    console.log('✅ Unemployment Rate (% change):');
    console.log(`  Series: ${data.title}`);
    console.log(`  Transform: ${data.units}`);
    if (data.data && data.data.length > 0) {
      console.log('  Recent changes:');
      data.data.slice(0, 5).forEach(obs => {
        console.log(`    ${obs.date}: ${obs.value?.toFixed(2)}%`);
      });
    }
  } catch (error) {
    console.error('❌ Error:', error.message);
  }
  
  console.log('\n✨ Testing complete!');
  process.exit(0);
}

// Run tests
testTools().catch(error => {
  console.error('Fatal error:', error);
  process.exit(1);
});