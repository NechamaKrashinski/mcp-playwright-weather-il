import asyncio
from contextlib import AsyncExitStack
from typing import Any
import os
import traceback

import httpx
from openai import OpenAI
from client import MCPClient
from dotenv import load_dotenv
from netfree_unstrict_ssl import unstrict_ssl

unstrict_ssl()
load_dotenv()


class ChatHost:
    def __init__(self):
        self.mcp_clients: list[MCPClient] = [MCPClient("./weather_USA.py"),MCPClient("./weather_Israel.py")]
        self.tool_clients: dict[str, tuple[MCPClient, str]] = {}
        self.clients_connected = False
        self.exit_stack = AsyncExitStack()
        # Initialize OpenAI client with API key from environment
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY environment variable not set")
        # Use custom httpx client to skip SSL verification (for Netfree)
        transport = httpx.HTTPTransport(verify=False)
        self.client = OpenAI(api_key=api_key, http_client=httpx.Client(transport=transport))

    async def connect_mcp_clients(self):
        """Connect all configured MCP clients once."""
        if self.clients_connected:
            return

        for client in self.mcp_clients:
            if client.session is None:
                await client.connect_to_server()

        if not self.mcp_clients:
            raise RuntimeError("No MCP clients are connected")

        self.clients_connected = True

    async def get_available_tools(self) -> list[dict[str, Any]]:
        """Collect tools from all MCP clients and map them back to their owner."""
        await self.connect_mcp_clients()
        self.tool_clients = {}
        available_tools: list[dict[str, Any]] = []

        for client in self.mcp_clients:
            if client.session is None:
                print(f"Warning: MCP client {client.client_name} is not connected, skipping")
                continue

            try:
                response = await client.session.list_tools()
                for tool in response.tools:
                    exposed_name = f"{client.client_name}__{tool.name}"
                    if exposed_name in self.tool_clients:
                        raise RuntimeError(f"Duplicate tool name detected: {exposed_name}")

                    self.tool_clients[exposed_name] = (client, tool.name)
                    available_tools.append(
                        {
                            "name": exposed_name,
                            "description": f"[{client.client_name}] {tool.description}",
                            "input_schema": tool.inputSchema,
                        }
                    )
            except Exception as e:
                print(f"Warning: Failed to get tools from {client.client_name}: {str(e)}")
                continue

        if not available_tools:
            raise RuntimeError("No tools available from any MCP client")

        return available_tools


    async def process_query(self, query: str) -> str:
        """Process a query using Claude and available tools"""
        messages = [{"role": "user", "content": query}]
        available_tools = await self.get_available_tools()
        final_text = []

        while True:
            # Convert tools format for OpenAI
            openai_tools = [
                {
                    "type": "function",
                    "function": {
                        "name": tool["name"],
                        "description": tool["description"],
                        "parameters": tool["input_schema"]
                    }
                }
                for tool in available_tools
            ]
            
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                max_tokens=1000,
                messages=messages,
                tools=openai_tools,
                tool_choice="auto"
            )

            assistant_message = response.choices[0].message
            tool_results = []
            saw_tool_use = False
            
            # Process message content
            if assistant_message.content:
                final_text.append(assistant_message.content)
            
            # Process tool calls
            if assistant_message.tool_calls:
                saw_tool_use = True
                for tool_call in assistant_message.tool_calls:
                    tool_name = tool_call.function.name
                    tool_args = tool_call.function.arguments
                    
                    # Parse JSON string if needed
                    if isinstance(tool_args, str):
                        import json
                        tool_args = json.loads(tool_args)

                    if tool_name not in self.tool_clients:
                        raise RuntimeError(f"Unknown tool requested by model: {tool_name}")

                    client, original_tool_name = self.tool_clients[tool_name]
                    if client.session is None:
                        raise RuntimeError(f"MCP client {client.client_name} is not connected")

                    result = await client.session.call_tool(original_tool_name, tool_args)
                    final_text.append(f"[Calling tool {tool_name} with args {tool_args}]")
                    tool_results.append(
                        {
                            "tool_call_id": tool_call.id,
                            "name": tool_name,
                            "content": str(result.content) if result.content else "",
                        }
                    )

            # Add assistant message with tool_calls to conversation
            messages.append({
                "role": "assistant",
                "content": assistant_message.content or "",
                "tool_calls": assistant_message.tool_calls if assistant_message.tool_calls else None
            })

            if not saw_tool_use:
                break

            # Add tool results as separate messages
            for tool_result in tool_results:
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_result["tool_call_id"],
                    "name": tool_result["name"],
                    "content": tool_result["content"]
                })

        return "\n".join(final_text)
    
    async def chat_loop(self):
        """Run an interactive chat loop"""
        print("\nMCP Client Started!")
        print("Type your queries or 'quit' to exit.")
        
        while True:
            try:
                query = input("\nQuery: ").strip()
                
                if query.lower() == 'quit':
                    break
                
                response = await self.process_query(query)
                print("\n" + response)
                
            except Exception as e:
                print(f"\nchat_loop Error: {str(e)}")
                traceback.print_exc()
                
    async def cleanup(self):
        """Clean up resources"""
        for client in reversed(self.mcp_clients):
            await client.cleanup()
        await self.exit_stack.aclose()
        
        
async def main():
    host = ChatHost()
    try:
        await host.chat_loop()
    finally:
        await host.cleanup()
        
if __name__ == "__main__":
    asyncio.run(main())
