# Identity

| UI login | Demo role |
|---|---|
| `reader` | BDC / internet sales, read-tier tools |
| `writer` | Sales manager, full tools plus offer approval |
| `admin` | Unused in the talk track |

AccessPolicy matches the agent ServiceAccount (`dealer-assistant` / `dealer-assistant-byo`), not the UI login. UserGroup JWT on MCP 401s initialize on this cluster because the UI-to-agent path does not send a bearer on agent-to-MCP. Group names are not required.

Optional: `scripts/get-token.sh` can fetch a password-grant token if you export `DEALERIQ_PASSWORD` (the password you type at the UI login). Direct grant is not required to run the demos.
