#!/bin/bash
# Usage: ./scripts/env-switch.sh [dev|prod]

set -e

case "$1" in
  dev|development)
    cp .env.development .env
    supabase link --project-ref ikdbhiozrtetognqcxbp
    echo "✓ Switched to DEVELOPMENT (test_blnd_backend)"
    ;;
  prod|production)
    cp .env.production .env
    supabase link --project-ref wtnbecnjsougjjcplhqf
    echo "✓ Switched to PRODUCTION (blnd_backend)"
    ;;
  status)
    echo "Current .env:"
    grep "SUPABASE_URL" .env | head -1
    echo ""
    echo "Supabase CLI linked to:"
    cat supabase/.temp/project-ref 2>/dev/null || echo "(not linked)"
    ;;
  *)
    echo "Usage: ./scripts/env-switch.sh [dev|prod|status]"
    echo ""
    echo "  dev    - Switch to test DB + test Supabase project"
    echo "  prod   - Switch to production DB + production Supabase project"
    echo "  status - Show current environment"
    exit 1
    ;;
esac
