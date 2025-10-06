IF DB_ID('edmund') IS NULL CREATE DATABASE edmund;
GO
USE edmund;
GO

IF OBJECT_ID('dbo.plc_artifacts') IS NULL
CREATE TABLE dbo.plc_artifacts(
  id INT IDENTITY PRIMARY KEY,
  kind NVARCHAR(24) NOT NULL,           -- FB|FC|OB|GlobalDB|InstanceDB
  number INT NULL,
  name NVARCHAR(256) NOT NULL,
  title NVARCHAR(512) NULL,
  path NVARCHAR(1024) NOT NULL,
  lang NVARCHAR(16) NULL,
  xml_raw XML NULL,
  source_text NVARCHAR(MAX) NULL,
  comment NVARCHAR(MAX) NULL
);
CREATE INDEX IX_plc_artifacts_kind_num ON dbo.plc_artifacts(kind, number);

IF OBJECT_ID('dbo.plc_tags') IS NULL
CREATE TABLE dbo.plc_tags(
  id INT IDENTITY PRIMARY KEY,
  tag_table NVARCHAR(128) NOT NULL,
  tag_name NVARCHAR(256) NOT NULL,
  data_type NVARCHAR(64) NOT NULL,
  address NVARCHAR(64) NULL,
  comment NVARCHAR(512) NULL,
  is_input BIT DEFAULT 0,
  is_output BIT DEFAULT 0,
  CONSTRAINT UQ_plc_tags UNIQUE(tag_table, tag_name)
);

IF OBJECT_ID('dbo.hardware_channels') IS NULL
CREATE TABLE dbo.hardware_channels(
  id INT IDENTITY PRIMARY KEY,
  device NVARCHAR(128) NOT NULL,
  module NVARCHAR(128) NOT NULL,
  channel NVARCHAR(64) NOT NULL,
  address NVARCHAR(64) NULL,
  signal_type NVARCHAR(32) NULL,
  comment NVARCHAR(512) NULL
);

IF OBJECT_ID('dbo.tag_usage') IS NULL
CREATE TABLE dbo.tag_usage(
  id INT IDENTITY PRIMARY KEY,
  tag_name NVARCHAR(256) NOT NULL,
  artifact_id INT NOT NULL FOREIGN KEY REFERENCES dbo.plc_artifacts(id),
  snippet NVARCHAR(1000) NULL
);

IF OBJECT_ID('dbo.docs') IS NULL
CREATE TABLE dbo.docs(
  id INT IDENTITY PRIMARY KEY,
  origin NVARCHAR(32) NOT NULL,     -- FB|FC|OB|GlobalDB|InstanceDB|TAG|HW|LOG
  ref NVARCHAR(256) NOT NULL,
  title NVARCHAR(512) NULL,
  text NVARCHAR(MAX) NOT NULL,
  meta NVARCHAR(MAX) NULL
);
