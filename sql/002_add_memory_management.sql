-- Migration: Add memory management columns to ops_operational_cases

-- Add columns for memory management
ALTER TABLE ops_operational_cases
ADD COLUMN IF NOT EXISTS memory_indexed_at TIMESTAMPTZ,
ADD COLUMN IF NOT EXISTS memory_error TEXT,
ADD COLUMN IF NOT EXISTS memory_content_version INTEGER;

-- Create index on memory_status for efficient filtering
CREATE INDEX IF NOT EXISTS idx_ops_case_memory_status ON ops_operational_cases(memory_status);

-- Create index on memory_indexed_at for timestamp ordering
CREATE INDEX IF NOT EXISTS idx_ops_case_memory_indexed_at ON ops_operational_cases(memory_indexed_at DESC);
