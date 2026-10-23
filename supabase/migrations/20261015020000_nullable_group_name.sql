-- A Blend with no chosen name stores null. The API fills display_name
-- from members' first names and does not write that string back here.
ALTER TABLE groups ALTER COLUMN name DROP NOT NULL;
