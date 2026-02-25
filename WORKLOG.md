# WORKLOG

Development history and feature changes for alittlebitofmoney.

## 2026-02-24

### Documentation
- Updated README.md with comprehensive project overview
- Added architecture diagram and project structure
- Documented L402 and Topup payment flows
- Added development guidelines for new endpoints
- Created WORKLOG.md for tracking changes

### Repository Setup
- Removed accidental trailing text from README
- Set up deployment to macmini production environment
- Configured SSH access between macmini and captain VPS

## Previous Work (Historical)

### Phase 3: Topup Mode
- Implemented prepaid balance system with Supabase backend
- Added bearer token authentication (`Authorization: Bearer <token>`)
- Built invoice creation and claim flow
- Added balance refill capability
- Implemented insufficient balance error handling

### Phase 2: Request Validation
- Added pre-invoice request validation
- Prevented invalid requests from creating Lightning invoices
- Implemented error codes: `missing_required_field`, `invalid_field_type`, `invalid_field_value`

### Phase 1: L402 Pay-Per-Request
- Implemented L402 protocol with macaroon-based auth
- Integrated Phoenix Lightning node client
- Built FastAPI proxy server
- Added OpenAI API endpoint proxying
- Implemented per-model pricing in config.yaml

### Frontend Development
- Built Vite + React SPA
- Created Catalog page with auto-generated code examples
- Implemented example-driven development workflow
- Added production build pipeline (frontend/dist)

### Testing Infrastructure
- Created E2E test suite consuming config.yaml examples
- Built topup flow integration tests
- Added unit test framework
- Configured test environment on captain VPS

### Deployment
- Created deploy.sh for local and prod environments
- Set up captain VPS with Phoenix node
- Configured GitHub Actions CI (if applicable)
- Documented server setup in SERVER_INFO.md

---

**Note**: Update this log whenever you add features, fix bugs, or make significant changes.
