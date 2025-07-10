# aria2 Client - BitTorrent Testing and Integration

## IMPORTANT: Project Context
This is a **standalone BitTorrent testing component** that integrates with the briefcase_ansible_test distributed torrent architecture. It provides aria2 RPC client functionality and seeder utilities for testing.

## Architecture Role
- **Component Type**: BitTorrent client library + test utilities
- **Integration**: Used by Ansible playbooks through JSON API
- **Scope**: aria2 daemon communication, torrent download testing

## CRITICAL: Coding Standards Compliance

### ✅ Current Code Already Follows Standards:
- **Immutable Configuration**: Uses `@dataclass(frozen=True)` for Aria2Config
- **Pure Functions**: Clean separation with helper functions
- **Fail-Fast Error Handling**: No silent failures or fallbacks
- **Complete Type Hints**: All functions have proper annotations
- **Context Managers**: Proper resource cleanup for aria2 processes
- **Function Size**: All functions under 50 lines

### YOU MUST Maintain These Patterns:
```python
# ✅ CORRECT - Immutable config
@dataclass(frozen=True)
class Aria2Config:
    host: str = "127.0.0.1"
    port: int = 6800
    secret: Optional[str] = None

# ✅ CORRECT - Pure function
def _calculate_file_hash(file_path: str) -> str:
    """Calculate SHA256 hash, no side effects."""
    # Implementation...

# ✅ CORRECT - Fail-fast error handling
def connect_to_aria2(config: Aria2Config) -> aria2p.API:
    """Connect to aria2 daemon, failing if unavailable."""
    # Let connection errors propagate
    return aria2p.API(aria2p.Client(host=config.host, port=config.port))
```

## NEVER Change These Design Decisions:
```python
# ❌ WRONG - Don't add fallbacks
try:
    api = connect_to_aria2(config)
except:
    return None  # NEVER hide connection failures!

# ❌ WRONG - Don't make config mutable
class Aria2Config:
    def __init__(self):
        self.host = "127.0.0.1"  # Should be frozen dataclass

# ❌ WRONG - Don't hide errors in tests
def test_download():
    try:
        result = download_torrent(magnet)
        assert result.success  # What if download_torrent throws?
    except:
        pass  # NEVER hide test failures!
```

## Integration Patterns

### Ansible Integration (Production):
```yaml
# ✅ CORRECT - Use aria2_client.py via Ansible
- name: Download torrent via aria2
  ansible.builtin.shell: >
    python3 aria2_client.py download 
    --magnet-link "{{ magnet_link }}"
    --timeout 3600
  vars:
    ansible_ssh_extra_args: "-L 6800:{{ inventory_hostname }}:6800"
```

### Testing Integration:
```python
# ✅ CORRECT - Direct API usage in tests
def test_magnet_download():
    config = Aria2Config(host="127.0.0.1", port=6800)
    with aria2_context_manager(config) as api:
        result = download_torrent(api, magnet_link)
        assert result.success
```

## Component Responsibilities

### aria2_client.py (KEEP - Core Component):
- **aria2 JSON-RPC Communication**: Direct API calls to daemon
- **Download Orchestration**: Add torrents, monitor progress
- **Error Handling**: aria2-specific error conditions
- **CLI Interface**: JSON output for Ansible consumption

### test_seeder.py (KEEP - Test Utility):
- **Test File Generation**: Random data for BitTorrent testing
- **Torrent Creation**: Generate .torrent files and magnet links
- **Seeding Operations**: Seed files for download testing

### test_aria2_client.py (KEEP - Development Only):
- **Unit Tests**: Verify aria2_client.py functionality
- **Integration Tests**: 40MB file transfer validation
- **Coverage**: Connection, download, pause/resume, statistics

## Testing Workflow

### Manual Integration Testing:
```bash
# 1. Start seeder for testing
python test_seeder.py

# 2. Copy magnet link from output

# 3. Run download test
pytest test_aria2_client.py::TestAria2Client::test_magnet_download -v
```

### Automated Testing:
```bash
# Install dependencies
pip install aria2p torf pytest pytest-asyncio torrentp

# Run all tests
pytest test_aria2_client.py -v
```

## File Organization

### KEEP These Files:
- **aria2_client.py**: Core functionality (well-designed)
- **test_seeder.py**: Essential for testing
- **test_data.py**: Utility functions for seeder
- **pyproject.toml**: Project configuration
- **README.md**: Documentation

### Development/Testing Only:
- **test_aria2_client.py**: Unit/integration tests
- **REFACTOR_RECOMMENDATIONS.md**: Architecture decisions

## Integration with Bastion Architecture
- **SSH Tunneling**: Handled by Ansible (`ansible_ssh_extra_args`)
- **VM Management**: Handled by do_vm_lifecycle.yml playbooks
- **File Transfer**: Handled by Ansible fetch/copy modules
- **Cleanup**: Handled by VM destruction in playbooks

**IMPORTANT**: aria2_client.py assumes localhost connection (127.0.0.1:6800) because Ansible establishes the SSH tunnel. Never add SSH tunneling logic to this component.