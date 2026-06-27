import type { McpPrefill } from "../components/ToolHubDiscover";

// Curated, NOT installed by default — one click pre-fills the MCP add form (user reviews + connects).
export const MCP_PRESETS: McpPrefill[] = [
  { label: "Everything (test)", transport: "stdio", command: "npx",
    args: ["-y", "@modelcontextprotocol/server-everything"], note: "Reference server with sample tools." },
  { label: "Filesystem", transport: "stdio", command: "npx",
    args: ["-y", "@modelcontextprotocol/server-filesystem"], note: "Append a directory path arg you want to expose." },
  { label: "Fetch", transport: "stdio", command: "npx",
    args: ["-y", "@modelcontextprotocol/server-fetch"], note: "Fetch & convert web pages." },
  { label: "Brave Search", transport: "stdio", command: "npx",
    args: ["-y", "@modelcontextprotocol/server-brave-search"], envKeys: ["BRAVE_API_KEY"], note: "Needs a Brave API key." },
  { label: "GitHub", transport: "stdio", command: "npx",
    args: ["-y", "@modelcontextprotocol/server-github"], envKeys: ["GITHUB_PERSONAL_ACCESS_TOKEN"], note: "Needs a GitHub PAT." },
];
