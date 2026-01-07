-- Create a table for public profiles (optional, but good practice)
-- create table profiles (
--   id uuid references auth.users not null,
--   updated_at timestamp with time zone,
--   username text unique,
--   avatar_url text,
--   website text,
--   primary key (id),
--   constraint username_length check (char_length(username) >= 3)
-- );
-- alter table profiles enable row level security;
-- create policy "Public profiles are viewable by everyone." on profiles for select using ( true );
-- create policy "Users can insert their own profile." on profiles for insert with check ( auth.uid() = id );
-- create policy "Users can update own profile." on profiles for update using ( auth.uid() = id );

-- Table for storing audio history
create table if not exists public.history (
  id uuid default gen_random_uuid() primary key,
  user_id uuid references auth.users(id) not null,
  url text not null,
  format text not null,
  created_at timestamp with time zone default timezone('utc'::text, now()) not null
);

-- Enable Row Level Security (RLS)
alter table public.history enable row level security;

-- Create policies
create policy "Users can insert their own history" 
on public.history for insert 
with check (auth.uid() = user_id);

create policy "Users can view their own history" 
on public.history for select 
using (auth.uid() = user_id);

create policy "Users can delete their own history" 
on public.history for delete 
using (auth.uid() = user_id);
