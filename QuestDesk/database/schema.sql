-- QuestDesk 1.0. Все изменения схемы выполняются транзакционно.
CREATE TYPE quest_status AS ENUM ('draft', 'active', 'completed', 'failed');
CREATE TYPE quest_difficulty AS ENUM ('easy', 'normal', 'hard');

CREATE TABLE users (
    id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name varchar(80) NOT NULL CHECK (length(trim(name)) > 0),
    xp integer NOT NULL DEFAULT 0 CHECK (xp >= 0),
    coins integer NOT NULL DEFAULT 0 CHECK (coins >= 0)
);
CREATE TABLE skills (
    id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id integer NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name varchar(80) NOT NULL CHECK (length(trim(name)) > 0),
    description text NOT NULL DEFAULT '',
    xp integer NOT NULL DEFAULT 0 CHECK (xp >= 0),
    UNIQUE (user_id, name)
);
CREATE TABLE quests (
    id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id integer NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title varchar(120) NOT NULL CHECK (length(trim(title)) > 0),
    description text NOT NULL DEFAULT '',
    difficulty quest_difficulty NOT NULL DEFAULT 'normal',
    status quest_status NOT NULL DEFAULT 'draft',
    due_date date,
    created_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    CHECK ((status IN ('completed','failed')) = (finished_at IS NOT NULL))
);
CREATE TABLE quest_steps (
    id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    quest_id integer NOT NULL REFERENCES quests(id) ON DELETE CASCADE,
    title varchar(200) NOT NULL CHECK (length(trim(title)) > 0),
    position integer NOT NULL CHECK (position >= 0),
    done boolean NOT NULL DEFAULT false,
    UNIQUE (quest_id, position)
);
CREATE TABLE quest_skills (
    quest_id integer NOT NULL REFERENCES quests(id) ON DELETE CASCADE,
    skill_id integer NOT NULL REFERENCES skills(id) ON DELETE RESTRICT,
    PRIMARY KEY (quest_id, skill_id)
);
CREATE TABLE rewards (
    id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id integer NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title varchar(120) NOT NULL CHECK (length(trim(title)) > 0),
    description text NOT NULL DEFAULT '',
    cost integer NOT NULL CHECK (cost BETWEEN 1 AND 100000),
    UNIQUE (user_id, title)
);
CREATE TABLE redemptions (
    id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id integer NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    reward_id integer REFERENCES rewards(id) ON DELETE SET NULL,
    reward_title varchar(120) NOT NULL,
    cost integer NOT NULL CHECK (cost > 0),
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE events (
    id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id integer NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    quest_id integer REFERENCES quests(id) ON DELETE SET NULL,
    kind varchar(30) NOT NULL CHECK (kind IN ('created','updated','started','step','completed','failed','deleted','redeemed','profile','catalog')),
    message text NOT NULL CHECK (length(trim(message)) > 0),
    payload jsonb NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(payload) = 'object'),
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_quests_user_status_due ON quests(user_id, status, due_date);
CREATE INDEX idx_quest_skills_skill ON quest_skills(skill_id);
CREATE INDEX idx_events_user_time ON events(user_id, created_at DESC);
CREATE INDEX idx_events_quest ON events(quest_id);
CREATE INDEX idx_redemptions_user_time ON redemptions(user_id, created_at DESC);
CREATE INDEX idx_redemptions_reward ON redemptions(reward_id);
CREATE INDEX idx_events_payload ON events USING gin(payload);
