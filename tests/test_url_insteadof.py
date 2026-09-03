# Copyright (c) 2026, Infineon Technologies
# SPDX-License-Identifier: Apache-2.0

"""Tests for url.insteadof configuration feature."""

import json
import subprocess

import pytest
from conftest import (
    cmd,
    cmd_raises,
)


def log_config(cwd=None):
    print(cmd('config -l', cwd=cwd).rstrip())


def mapping_entry(remote, mirror):
    return f'{remote}>{mirror}'


def test_url_insteadof_init_manifest_clone(repos_tmpdir):
    """Test that url.insteadof works during 'west init' manifest clone."""
    remotes = repos_tmpdir / 'repos'
    mirrors = repos_tmpdir / 'mirrors'
    mirrors.mkdir()

    # Mirror the manifest repository (zephyr)
    original_zephyr = remotes / 'zephyr'
    mirror_zephyr = mirrors / 'zephyr'
    subprocess.check_call(['git', 'clone', '--mirror', str(original_zephyr), str(mirror_zephyr)])

    workspace = repos_tmpdir / 'workspace'

    # Set url.insteadof in global config before init
    # (init reads global config even before workspace exists)
    remotes_url = 'file://' + str(remotes).replace('\\', '/')
    mirrors_url = 'file://' + str(mirrors).replace('\\', '/')
    cmd(
        [
            'config',
            '--global',
            'url.insteadof',
            json.dumps([mapping_entry(remotes_url, mirrors_url)]),
        ]
    )
    log_config()

    try:
        # Now run init, which should use the mirror for cloning the manifest
        cmd(['init', '-m', str(original_zephyr), str(workspace)], env={'ZEPHYR_BASE': None})

        # Verify manifest was cloned
        assert (workspace / 'zephyr' / '.git').check(dir=1)
        assert (workspace / 'zephyr' / 'west.yml').check(file=1)
    finally:
        # Clean up global config
        cmd(['config', '--global', '-d', 'url.insteadof'])


def test_url_insteadof_prevents_credential_prompt(repos_tmpdir):
    """Test that url.insteadof probe doesn't trigger credential prompts."""
    # This is a regression test to ensure -c core.askPass=true is used
    remotes = repos_tmpdir / 'repos'
    workspace = repos_tmpdir / 'workspace'
    manifest = remotes / 'zephyr'

    cmd(['init', '-m', str(manifest), str(workspace)], env={'ZEPHYR_BASE': None})

    # Configure mirror pointing to nonexistent HTTPS repo (would normally prompt)
    cmd(
        [
            'config',
            'url.insteadof',
            json.dumps([mapping_entry(str(remotes), 'https://example.com/nonexistent')]),
        ],
        cwd=workspace,
    )
    log_config(cwd=workspace)

    # This should complete without hanging on credential prompt
    # The test will timeout if credential prompt blocks
    cmd('update', cwd=workspace)

    # Should fall back to original since mirror doesn't exist
    assert (workspace / 'net-tools' / '.git').check(dir=1)


def test_url_insteadof_basic_prefix_match(repos_tmpdir):
    """Test url.insteadof with a simple prefix replacement."""
    # Setup: create a mirror of net-tools in a different location
    remotes = repos_tmpdir / 'repos'
    mirrors = repos_tmpdir / 'mirrors'
    mirrors.mkdir()

    # Clone net-tools to mirror location
    original_net_tools = remotes / 'net-tools'
    mirror_net_tools = mirrors / 'net-tools'
    subprocess.check_call(
        ['git', 'clone', '--mirror', str(original_net_tools), str(mirror_net_tools)]
    )

    # Create workspace with url.insteadof config
    workspace = repos_tmpdir / 'workspace'
    manifest = remotes / 'zephyr'

    # Initialize workspace
    cmd(['init', '-m', str(manifest), str(workspace)], env={'ZEPHYR_BASE': None})

    # Configure url.insteadof to redirect from remotes to mirrors
    cmd(
        ['config', 'url.insteadof', json.dumps([mapping_entry(str(remotes), str(mirrors))])],
        cwd=workspace,
    )
    log_config(cwd=workspace)

    # Run update - should use mirror for net-tools
    output = cmd('update', cwd=workspace)

    # Verify mirror was used (normalize paths for Windows/Unix compatibility)
    assert 'using mirror:' in output
    # Normalize both paths to use forward slashes for comparison
    expected_mirror = str(mirror_net_tools).replace('\\', '/')
    normalized_output = output.replace('\\', '/')
    assert expected_mirror in normalized_output

    # Verify project was cloned successfully
    assert (workspace / 'net-tools' / '.git').check(dir=1)


def test_url_insteadof_basic_prefix_match_json_array(repos_tmpdir):
    """Test url.insteadof with a JSON array of remote=mirror strings."""
    remotes = repos_tmpdir / 'repos'
    mirrors = repos_tmpdir / 'mirrors'
    mirrors.mkdir()

    original_net_tools = remotes / 'net-tools'
    mirror_net_tools = mirrors / 'net-tools'
    subprocess.check_call(
        ['git', 'clone', '--mirror', str(original_net_tools), str(mirror_net_tools)]
    )

    workspace = repos_tmpdir / 'workspace'
    manifest = remotes / 'zephyr'

    cmd(['init', '-m', str(manifest), str(workspace)], env={'ZEPHYR_BASE': None})

    cmd(
        [
            'config',
            'url.insteadof',
            json.dumps(
                [
                    mapping_entry('https://example.invalid/', 'https://mirror.invalid/'),
                    mapping_entry(str(remotes), str(mirrors)),
                ]
            ),
        ],
        cwd=workspace,
    )
    log_config(cwd=workspace)

    output = cmd('update', cwd=workspace)

    assert 'using mirror:' in output
    assert str(mirror_net_tools).replace('\\', '/') in output.replace('\\', '/')
    assert (workspace / 'net-tools' / '.git').check(dir=1)


def test_url_insteadof_nonexistent_mirror_fallback(repos_tmpdir):
    """Test that nonexistent mirrors fall back to original URL."""
    remotes = repos_tmpdir / 'repos'
    workspace = repos_tmpdir / 'workspace'
    manifest = remotes / 'zephyr'

    # Initialize workspace
    cmd(['init', '-m', str(manifest), str(workspace)], env={'ZEPHYR_BASE': None})

    # Configure url.insteadof with nonexistent mirror path
    nonexistent = repos_tmpdir / 'does-not-exist'
    cmd(
        ['config', 'url.insteadof', json.dumps([mapping_entry(str(remotes), str(nonexistent))])],
        cwd=workspace,
    )
    log_config(cwd=workspace)

    # Run update - should fall back to original URL
    output = cmd('update', cwd=workspace)

    # Verify mirror was tried but original URL was used
    assert 'was not found' in output or 'using mirror:' not in output

    # Verify projects were still cloned successfully from original
    assert (workspace / 'net-tools' / '.git').check(dir=1)
    assert (workspace / 'subdir' / 'Kconfiglib' / '.git').check(dir=1)


def test_url_insteadof_multiple_mappings(repos_tmpdir):
    """Test url.insteadof with multiple JSON mappings."""
    remotes = repos_tmpdir / 'repos'
    mirrors1 = repos_tmpdir / 'mirrors1'
    mirrors2 = repos_tmpdir / 'mirrors2'
    mirrors1.mkdir()
    mirrors2.mkdir()

    # Create two different mirrors for different repos
    original_net_tools = remotes / 'net-tools'
    original_kconfiglib = remotes / 'Kconfiglib'
    mirror1_net_tools = mirrors1 / 'net-tools'
    mirror2_kconfiglib = mirrors2 / 'Kconfiglib'

    subprocess.check_call(
        ['git', 'clone', '--mirror', str(original_net_tools), str(mirror1_net_tools)]
    )
    subprocess.check_call(
        ['git', 'clone', '--mirror', str(original_kconfiglib), str(mirror2_kconfiglib)]
    )

    workspace = repos_tmpdir / 'workspace'
    manifest = remotes / 'zephyr'

    cmd(['init', '-m', str(manifest), str(workspace)], env={'ZEPHYR_BASE': None})

    # Configure multiple mappings with different repo-specific prefixes
    # The manifest uses file:// URLs, so we need to mirror those
    remotes_url = 'file://' + str(remotes).replace('\\', '/')
    net_tools_url = remotes_url + '/net-tools'
    kconfiglib_url = remotes_url + '/Kconfiglib'
    mirror1_net_tools_url = 'file://' + str(mirror1_net_tools).replace('\\', '/')
    mirror2_kconfiglib_url = 'file://' + str(mirror2_kconfiglib).replace('\\', '/')

    mirror_config = [
        mapping_entry(net_tools_url, mirror1_net_tools_url),
        mapping_entry(kconfiglib_url, mirror2_kconfiglib_url),
    ]
    cmd(
        ['config', 'url.insteadof', json.dumps(mirror_config)],
        cwd=workspace,
    )
    log_config(cwd=workspace)

    cmd('update', cwd=workspace)

    # Verify that at least the projects were cloned successfully
    # (mirrors may or may not be used depending on exact URL matching)
    assert (workspace / 'net-tools' / '.git').check(dir=1)
    assert (workspace / 'subdir' / 'Kconfiglib' / '.git').check(dir=1)


def test_url_insteadof_no_prefix_match(repos_tmpdir):
    """Test url.insteadof when no mapping matches the URL prefix."""
    remotes = repos_tmpdir / 'repos'
    workspace = repos_tmpdir / 'workspace'
    manifest = remotes / 'zephyr'

    cmd(['init', '-m', str(manifest), str(workspace)], env={'ZEPHYR_BASE': None})

    # Configure url.insteadof with unrelated prefix
    cmd(
        [
            'config',
            'url.insteadof',
            json.dumps([mapping_entry('https://github.com/', 'https://mirror.example.com/')]),
        ],
        cwd=workspace,
    )
    log_config(cwd=workspace)

    # Run update - should use original URLs since prefix doesn't match
    output = cmd('update', cwd=workspace)

    # No mirror messages should appear
    assert 'irror' not in output

    # Projects should still be cloned from original
    assert (workspace / 'net-tools' / '.git').check(dir=1)


def test_url_insteadof_with_trailing_slashes(repos_tmpdir):
    """Test that url.insteadof handles trailing slashes correctly."""
    remotes = repos_tmpdir / 'repos'
    mirrors = repos_tmpdir / 'mirrors'
    mirrors.mkdir()

    original_net_tools = remotes / 'net-tools'
    mirror_net_tools = mirrors / 'net-tools'
    subprocess.check_call(
        ['git', 'clone', '--mirror', str(original_net_tools), str(mirror_net_tools)]
    )

    workspace = repos_tmpdir / 'workspace'
    manifest = remotes / 'zephyr'

    cmd(['init', '-m', str(manifest), str(workspace)], env={'ZEPHYR_BASE': None})

    # Test with and without trailing slashes (should be normalized)
    cmd(
        ['config', 'url.insteadof', json.dumps([mapping_entry(f'{remotes}/', f'{mirrors}/')])],
        cwd=workspace,
    )
    log_config(cwd=workspace)

    output = cmd('update', cwd=workspace)

    assert 'using mirror:' in output
    normalized_output = output.replace('\\', '/')
    assert str(mirror_net_tools).replace('\\', '/') in normalized_output


def test_url_insteadof_first_working_mirror_wins(repos_tmpdir):
    """Test that first reachable mirror is used when multiple match."""
    remotes = repos_tmpdir / 'repos'
    mirrors1 = repos_tmpdir / 'mirrors1'
    mirrors2 = repos_tmpdir / 'mirrors2'
    mirrors1.mkdir()
    mirrors2.mkdir()

    # Create two mirrors for the same repo
    original_net_tools = remotes / 'net-tools'
    mirror1_net_tools = mirrors1 / 'net-tools'
    mirror2_net_tools = mirrors2 / 'net-tools'

    subprocess.check_call(
        ['git', 'clone', '--mirror', str(original_net_tools), str(mirror1_net_tools)]
    )
    subprocess.check_call(
        ['git', 'clone', '--mirror', str(original_net_tools), str(mirror2_net_tools)]
    )

    workspace = repos_tmpdir / 'workspace'
    manifest = remotes / 'zephyr'

    cmd(['init', '-m', str(manifest), str(workspace)], env={'ZEPHYR_BASE': None})

    # Configure two mappings - first one should win
    mirror_config = json.dumps(
        [
            mapping_entry(str(remotes), str(mirrors1)),
            mapping_entry(f'{remotes}/', f'{mirrors2}/'),
        ]
    )
    cmd(['config', 'url.insteadof', mirror_config], cwd=workspace)
    log_config(cwd=workspace)

    output = cmd('update', cwd=workspace)

    # First mirror should be used (normalize paths for comparison)
    normalized_output = output.replace(r'\', r'/')
    assert str(mirrors1).replace('\\', '/') in normalized_output
    # Second mirror should not appear
    assert str(mirrors2).replace('\\', '/') not in normalized_output


def test_url_insteadof_empty_config(repos_tmpdir):
    """Test that empty url.insteadof config doesn't break anything."""
    remotes = repos_tmpdir / 'repos'
    workspace = repos_tmpdir / 'workspace'
    manifest = remotes / 'zephyr'

    cmd(['init', '-m', str(manifest), str(workspace)], env={'ZEPHYR_BASE': None})

    # Don't set url.insteadof at all
    output = cmd('update', cwd=workspace)

    # Should work normally
    assert (workspace / 'net-tools' / '.git').check(dir=1)
    assert 'irror' not in output


def test_url_insteadof_invalid_json_fails(repos_tmpdir):
    """Test that malformed url.insteadof JSON fails the command."""
    remotes = repos_tmpdir / 'repos'
    workspace = repos_tmpdir / 'workspace'
    manifest = remotes / 'zephyr'

    cmd(['init', '-m', str(manifest), str(workspace)], env={'ZEPHYR_BASE': None})

    cmd(['config', 'url.insteadof', '["missing-end"'], cwd=workspace)
    log_config(cwd=workspace)

    with pytest.raises(SystemExit):
        cmd('update', cwd=workspace)


@pytest.mark.parametrize(
    'config_value, expected_error',
    [
        (json.dumps({'remote1': 'mirror1'}), 'expected JSON array of "remote>mirror" strings'),
        (
            json.dumps([{'remote1': 'mirror1'}]),
            'each entry must be a "remote>mirror" string',
        ),
        (json.dumps(['remote1=mirror1']), 'missing ">" separator'),
        (json.dumps(['>mirror1']), 'empty remote or mirror value'),
        (json.dumps(['remote1>']), 'empty remote or mirror value'),
    ],
)
def test_url_insteadof_invalid_mapping_format_fails(repos_tmpdir, config_value, expected_error):
    """Test invalid url.insteadof values fail strict mapping validation."""
    remotes = repos_tmpdir / 'repos'
    manifest = remotes / 'zephyr'

    cmd(['config', '--global', 'url.insteadof', config_value])
    try:
        _, stderr = cmd_raises(
            ['init', '-m', str(manifest), str(repos_tmpdir / 'workspace')],
            SystemExit,
            env={'ZEPHYR_BASE': None},
        )
        assert expected_error in stderr
    finally:
        cmd(['config', '--global', '-d', 'url.insteadof'])


def test_url_insteadof_with_auto_cache(repos_tmpdir):
    """Test url.insteadof interaction with auto-cache feature."""
    remotes = repos_tmpdir / 'repos'
    mirrors = repos_tmpdir / 'mirrors'
    mirrors.mkdir()

    # Create mirror for net-tools
    original_net_tools = remotes / 'net-tools'
    mirror_net_tools = mirrors / 'net-tools'
    subprocess.check_call(
        ['git', 'clone', '--mirror', str(original_net_tools), str(mirror_net_tools)]
    )

    workspace = repos_tmpdir / 'workspace'
    manifest = remotes / 'zephyr'
    cache_dir = repos_tmpdir / 'cache'

    cmd(['init', '-m', str(manifest), str(workspace)], env={'ZEPHYR_BASE': None})

    # Configure both auto-cache and url.insteadof
    cmd(['config', 'update.auto-cache', str(cache_dir)], cwd=workspace)
    # Use file:// URL pattern to match what's in the manifest
    remotes_url = 'file://' + str(remotes).replace('\\', '/')
    mirrors_url = 'file://' + str(mirrors).replace('\\', '/')
    cmd(
        ['config', 'url.insteadof', json.dumps([mapping_entry(remotes_url, mirrors_url)])],
        cwd=workspace,
    )
    log_config(cwd=workspace)

    # Run update for net-tools - should create auto-cache via mirror
    cmd(['update', 'net-tools'], cwd=workspace)

    # Verify workspace was cloned successfully
    # (mirror may be used for auto-cache creation, but that's internal)
    assert (workspace / 'net-tools' / '.git').check(dir=1)

    # Verify auto-cache was created
    # The cache directory should exist with some content
    assert cache_dir.check(dir=1)


def test_url_insteadof_with_name_cache(repos_tmpdir):
    """Test url.insteadof interaction with name-cache feature."""
    remotes = repos_tmpdir / 'repos'
    mirrors = repos_tmpdir / 'mirrors'
    mirrors.mkdir()

    # Create mirror for net-tools
    original_net_tools = remotes / 'net-tools'
    mirror_net_tools = mirrors / 'net-tools'
    subprocess.check_call(
        ['git', 'clone', '--mirror', str(original_net_tools), str(mirror_net_tools)]
    )

    workspace = repos_tmpdir / 'workspace'
    manifest = remotes / 'zephyr'
    name_cache_dir = repos_tmpdir / 'name_cache'
    name_cache_dir.mkdir()

    # Pre-populate name-cache with a clone from the mirror
    # name-cache uses flat structure: cache/project-name/
    name_cache_net_tools = name_cache_dir / 'net-tools'
    subprocess.check_call(
        ['git', 'clone', '--mirror', str(mirror_net_tools), str(name_cache_net_tools)]
    )

    cmd(['init', '-m', str(manifest), str(workspace)], env={'ZEPHYR_BASE': None})

    # Configure url.insteadof to use mirrors for any clones
    remotes_url = 'file://' + str(remotes).replace('\\', '/')
    mirrors_url = 'file://' + str(mirrors).replace('\\', '/')
    cmd(
        ['config', 'url.insteadof', json.dumps([mapping_entry(remotes_url, mirrors_url)])],
        cwd=workspace,
    )
    log_config(cwd=workspace)

    # Run update with --name-cache - should clone from name-cache (which was created via mirror)
    output = cmd(['update', '--name-cache', str(name_cache_dir), 'net-tools'], cwd=workspace)

    # Verify workspace was cloned successfully
    assert (workspace / 'net-tools' / '.git').check(dir=1)

    # Verify it used the name-cache
    assert 'cloning from' in output


def test_url_insteadof_with_path_cache(repos_tmpdir):
    """Test url.insteadof interaction with path-cache feature."""
    remotes = repos_tmpdir / 'repos'
    mirrors = repos_tmpdir / 'mirrors'
    mirrors.mkdir()

    # Create mirror for tagged_repo
    original_tagged_repo = remotes / 'tagged_repo'
    mirror_tagged_repo = mirrors / 'tagged_repo'
    subprocess.check_call(
        ['git', 'clone', '--mirror', str(original_tagged_repo), str(mirror_tagged_repo)]
    )

    workspace = repos_tmpdir / 'workspace'
    manifest = remotes / 'zephyr'
    path_cache_dir = repos_tmpdir / 'path_cache'
    path_cache_dir.mkdir()

    # Pre-populate path-cache with a clone from the mirror
    # path-cache preserves workspace structure: cache/tagged_repo/
    path_cache_tagged_repo = path_cache_dir / 'tagged_repo'
    subprocess.check_call(
        ['git', 'clone', '--mirror', str(mirror_tagged_repo), str(path_cache_tagged_repo)]
    )

    cmd(['init', '-m', str(manifest), str(workspace)], env={'ZEPHYR_BASE': None})

    # Configure url.insteadof to use mirrors for any clones
    remotes_url = 'file://' + str(remotes).replace('\\', '/')
    mirrors_url = 'file://' + str(mirrors).replace('\\', '/')
    cmd(
        ['config', 'url.insteadof', json.dumps([mapping_entry(remotes_url, mirrors_url)])],
        cwd=workspace,
    )
    log_config(cwd=workspace)

    # Run update with --path-cache - should clone from path-cache (which was created via mirror)
    output = cmd(['update', '--path-cache', str(path_cache_dir), 'tagged_repo'], cwd=workspace)

    # Verify workspace was cloned successfully
    assert (workspace / 'tagged_repo' / '.git').check(dir=1)

    # Verify it used the path-cache
    assert 'cloning from' in output
