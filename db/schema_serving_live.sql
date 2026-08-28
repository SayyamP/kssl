-- serving_live: what the API actually serves. Reference rows are the
-- archive; only pipeline-origin rows go to the UI. ui_config passes
-- through (interface vocabulary, not data).
CREATE SCHEMA IF NOT EXISTS serving_live;
CREATE OR REPLACE VIEW serving_live.company_source AS SELECT * FROM serving.company_source WHERE origin = 'pipeline';
CREATE OR REPLACE VIEW serving_live.competitors AS SELECT * FROM serving.competitors WHERE origin = 'pipeline';
CREATE OR REPLACE VIEW serving_live.geo_comp AS SELECT * FROM serving.geo_comp WHERE origin = 'pipeline';
CREATE OR REPLACE VIEW serving_live.geo_presence AS SELECT * FROM serving.geo_presence WHERE origin = 'pipeline';
CREATE OR REPLACE VIEW serving_live.innovation AS SELECT * FROM serving.innovation WHERE origin = 'pipeline';
CREATE OR REPLACE VIEW serving_live.matchup AS SELECT * FROM serving.matchup WHERE origin = 'pipeline';
CREATE OR REPLACE VIEW serving_live.partner AS SELECT * FROM serving.partner WHERE origin = 'pipeline';
CREATE OR REPLACE VIEW serving_live.patent AS SELECT * FROM serving.patent WHERE origin = 'pipeline';
CREATE OR REPLACE VIEW serving_live.signal_card AS SELECT * FROM serving.signal_card WHERE origin = 'pipeline';
CREATE OR REPLACE VIEW serving_live.signal_detail AS SELECT * FROM serving.signal_detail WHERE origin = 'pipeline';
CREATE OR REPLACE VIEW serving_live.source_registry AS SELECT * FROM serving.source_registry WHERE origin = 'pipeline';
CREATE OR REPLACE VIEW serving_live.tender AS SELECT * FROM serving.tender WHERE origin = 'pipeline';
CREATE OR REPLACE VIEW serving_live.ui_config AS SELECT * FROM serving.ui_config;
