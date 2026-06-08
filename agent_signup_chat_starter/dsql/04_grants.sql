GRANT USAGE ON DATABASE starter TO ROLE base_demo_role;
GRANT USAGE ON SCHEMA public TO ROLE base_demo_role;
GRANT SELECT ON RELATION starter.public.pageviews_mview TO ROLE base_demo_role;
