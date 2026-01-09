"""Live viewer for Polymarket Copy Bot activities."""

import os
import re
import sys
import time
import glob
from datetime import datetime

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

# Wallet address for live mode API queries
PROXY_WALLET = "0x9c76847744942b41d3bbdcfe5a3b98ae67a95750"

# ANSI color codes for terminal
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    DIM = '\033[2m'


def clear_screen():
    """Clear the terminal screen."""
    os.system('cls' if os.name == 'nt' else 'clear')


def get_latest_log_file():
    """Get the most recent bot log file."""
    # Use the directory where this script is located
    script_dir = os.path.dirname(os.path.abspath(__file__))
    log_pattern = os.path.join(script_dir, "bot_*.log")
    log_files = glob.glob(log_pattern)
    if not log_files:
        return None
    return max(log_files, key=os.path.getmtime)


def tail_log(filepath: str, num_lines: int = 500):
    """Read the last N lines from a file."""
    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
            return lines[-num_lines:]
    except Exception as e:
        return [f"Error reading log: {e}"]


def parse_status_from_log(lines: list) -> dict:
    """Parse the latest paper trading status from log lines."""
    status = {
        "runtime_hours": 0,
        "usdc_balance": 0,
        "portfolio_value": 0,
        "pnl": 0,
        "pnl_percent": 0,
        "trades_detected": 0,
        "trades_copied": 0,
        "trades_skipped": 0,
        "open_positions": 0,
        "positions": []
    }

    # Find the last status block
    in_status_block = False
    in_positions_block = False

    for line in reversed(lines):
        if "PAPER TRADING STATUS" in line:
            break

        # Parse status values
        if "Runtime:" in line:
            match = re.search(r'Runtime:\s*([\d.]+)\s*hours', line)
            if match:
                status["runtime_hours"] = float(match.group(1))
        elif "USDC Balance:" in line:
            match = re.search(r'USDC Balance:\s*\$([\d.]+)', line)
            if match:
                status["usdc_balance"] = float(match.group(1))
        elif "Portfolio Value:" in line:
            match = re.search(r'Portfolio Value:\s*\$([\d.]+)', line)
            if match:
                status["portfolio_value"] = float(match.group(1))
        elif "P&L:" in line and "%" in line:
            match = re.search(r'P&L:\s*\$?([-\d.]+)\s*\(([-\d.]+)%\)', line)
            if match:
                status["pnl"] = float(match.group(1))
                status["pnl_percent"] = float(match.group(2))
        elif "Trades Detected:" in line:
            match = re.search(r'Trades Detected:\s*(\d+)', line)
            if match:
                status["trades_detected"] = int(match.group(1))
        elif "Trades Copied:" in line:
            match = re.search(r'Trades Copied:\s*(\d+)', line)
            if match:
                status["trades_copied"] = int(match.group(1))
        elif "Trades Skipped:" in line:
            match = re.search(r'Trades Skipped:\s*(\d+)', line)
            if match:
                status["trades_skipped"] = int(match.group(1))
        elif "Open Positions:" in line:
            match = re.search(r'Open Positions:\s*(\d+)', line)
            if match:
                status["open_positions"] = int(match.group(1))
        elif "shares @" in line:
            # Parse position line like "  Ethereum Up or Down - January : 76.7147 shares @ $0.3852"
            match = re.search(r'^\s+(.+?):\s*([\d.]+)\s*shares\s*@\s*\$([\d.]+)', line)
            if match:
                status["positions"].append({
                    "name": match.group(1).strip(),
                    "shares": float(match.group(2)),
                    "price": float(match.group(3))
                })

    return status


def get_live_portfolio() -> dict:
    """Fetch live portfolio data from API."""
    if not HAS_REQUESTS:
        return None
    
    try:
        # Get positions
        resp = requests.get(
            f'https://data-api.polymarket.com/positions?user={PROXY_WALLET}&sizeThreshold=0',
            timeout=5
        )
        positions = resp.json() if resp.status_code == 200 else []
        
        # Calculate totals
        total_value = sum(float(p.get('currentValue', 0) or 0) for p in positions)
        total_cost = sum(float(p.get('size', 0) or 0) * float(p.get('avgPrice', 0) or 0) for p in positions)
        pnl = total_value - total_cost
        pnl_pct = (pnl / total_cost * 100) if total_cost > 0 else 0
        
        # Get USDC balance (try gamma API)
        usdc_balance = 0
        try:
            cash_resp = requests.get(f'https://gamma-api.polymarket.com/users/{PROXY_WALLET}', timeout=3)
            if cash_resp.status_code == 200:
                cash = cash_resp.json()
                usdc_balance = float(cash.get('usdcBalance', 0) or 0)
        except:
            pass
        
        # Format positions for display
        formatted_positions = []
        for p in positions:
            size = float(p.get('size', 0) or 0)
            if size < 0.1:
                continue
            avg_price = float(p.get('avgPrice', 0) or 0)
            cur_price = float(p.get('curPrice', 0) or 0)
            formatted_positions.append({
                "name": p.get('title', '')[:40],
                "outcome": p.get('outcome', ''),
                "shares": size,
                "price": cur_price,
                "cost": size * avg_price,
                "value": float(p.get('currentValue', 0) or 0),
            })
        
        open_positions = len([p for p in positions if float(p.get('size', 0) or 0) > 0])
        
        return {
            "usdc_balance": usdc_balance,
            "portfolio_value": total_value,
            "total_cost": total_cost,
            "pnl": pnl,
            "pnl_percent": pnl_pct,
            "open_positions": open_positions,
            "positions": formatted_positions,
        }
    except Exception as e:
        return None


def get_recent_trades(lines: list, max_trades: int = 20) -> list:
    """Extract recent trade activity from log lines."""
    trades = []

    for line in lines:
        timestamp = line[:19] if len(line) > 19 else ""

        if "NEW TRADE DETECTED FROM TARGET" in line:
            trades.append({"type": "detected", "time": timestamp, "msg": "New trade detected"})
        elif "Market:" in line and "Side:" not in line:
            match = re.search(r'Market:\s*(.+)', line)
            if match and trades:
                trades[-1]["market"] = match.group(1).strip()
        elif "Side:" in line and "Amount:" in line:
            match = re.search(r'Side:\s*(\w+)\s*\|\s*Amount:\s*\$([\d.]+)', line)
            if match and trades:
                trades[-1]["side"] = match.group(1)
                trades[-1]["amount"] = match.group(2)
        elif "[DRY RUN] Paper trade executed:" in line:
            match = re.search(r'Paper trade executed:\s*(\w+)\s*\$([\d.]+)\s*@\s*([\d.]+)', line)
            if match:
                trades.append({
                    "type": "executed",
                    "time": timestamp,
                    "side": match.group(1),
                    "amount": match.group(2),
                    "price": match.group(3)
                })
        elif "Trade copied successfully" in line:
            trades.append({"type": "success", "time": timestamp, "msg": "Trade copied!"})
        elif "Trade SKIPPED:" in line:
            match = re.search(r'Trade SKIPPED:\s*(.+)', line)
            reason = match.group(1) if match else "unknown"
            trades.append({"type": "skipped", "time": timestamp, "reason": reason})
        elif "SKIP:" in line:
            match = re.search(r'SKIP:\s*(.+)', line)
            if match:
                trades.append({"type": "filtered", "time": timestamp, "msg": match.group(1)})
        elif "COPY:" in line:
            match = re.search(r'COPY:\s*(.+)', line)
            if match:
                trades.append({"type": "copy", "time": timestamp, "msg": match.group(1)})
        elif "HEDGE SKIP:" in line:
            match = re.search(r'HEDGE SKIP:\s*(.+)', line)
            if match:
                trades.append({"type": "hedge_skip", "time": timestamp, "msg": match.group(1)})
        elif "DOMINANT SKIP:" in line:
            match = re.search(r'DOMINANT SKIP:\s*(.+)', line)
            if match:
                trades.append({"type": "dominant_skip", "time": timestamp, "msg": match.group(1)})
        elif "SKIP OPPOSITE:" in line:
            match = re.search(r'SKIP OPPOSITE:\s*(.+)', line)
            if match:
                trades.append({"type": "opposite_skip", "time": timestamp, "msg": match.group(1)})

    return trades[-max_trades:]


def count_trades_from_log(lines: list) -> dict:
    """Count trade statistics from log lines."""
    detected = 0
    copied = 0
    skipped = 0

    for line in lines:
        if "NEW TRADE DETECTED FROM TARGET" in line:
            detected += 1
        elif "Trade copied successfully" in line:
            copied += 1
        elif "Trade SKIPPED:" in line or "SKIP:" in line or "HEDGE SKIP:" in line or "DOMINANT SKIP:" in line or "SKIP OPPOSITE:" in line:
            skipped += 1

    return {
        "trades_detected": detected,
        "trades_copied": copied,
        "trades_skipped": skipped,
    }


def format_pnl(pnl: float) -> str:
    """Format P&L with color."""
    if pnl > 0:
        return f"{Colors.GREEN}+${pnl:.2f}{Colors.ENDC}"
    elif pnl < 0:
        return f"{Colors.RED}-${abs(pnl):.2f}{Colors.ENDC}"
    else:
        return f"${pnl:.2f}"


def format_pnl_percent(pnl_pct: float) -> str:
    """Format P&L percentage with color."""
    if pnl_pct > 0:
        return f"{Colors.GREEN}+{pnl_pct:.2f}%{Colors.ENDC}"
    elif pnl_pct < 0:
        return f"{Colors.RED}{pnl_pct:.2f}%{Colors.ENDC}"
    else:
        return f"{pnl_pct:.2f}%"


def display_dashboard():
    """Display the live dashboard."""
    clear_screen()

    # Detect mode from .env file
    is_live_mode = False
    script_dir = os.path.dirname(os.path.abspath(__file__))
    env_file = os.path.join(script_dir, ".env")
    if os.path.exists(env_file):
        with open(env_file, 'r') as f:
            env_content = f.read().lower()
            # Check for DRY_RUN=false or DRY_RUN=0 (case insensitive)
            if 'dry_run=false' in env_content or 'dry_run=0' in env_content:
                is_live_mode = True

    mode_str = "LIVE MODE" if is_live_mode else "DRY RUN"
    mode_color = Colors.RED if is_live_mode else Colors.YELLOW

    print(f"{Colors.BOLD}{Colors.CYAN}")
    print("=" * 70)
    print(f"         POLYMARKET COPY BOT - LIVE MONITOR ({mode_color}{mode_str}{Colors.CYAN})")
    print("=" * 70)
    print(f"{Colors.ENDC}")

    # Get latest log file
    log_file = get_latest_log_file()

    print(f"{Colors.DIM}Log file: {log_file or 'None found'}{Colors.ENDC}")
    print(f"{Colors.DIM}Updated: {datetime.now().strftime('%H:%M:%S')}{Colors.ENDC}")
    print()

    if not log_file:
        print(f"{Colors.YELLOW}No bot log file found. Start the bot first.{Colors.ENDC}")
        return

    # Read log file
    lines = tail_log(log_file, 500)

    # Parse status from log (for trade stats)
    status = parse_status_from_log(lines)

    # Count trades from log
    trade_counts = count_trades_from_log(lines)
    status.update(trade_counts)

    # Get portfolio data - use API for live mode, log parsing for dry run
    if is_live_mode and HAS_REQUESTS:
        live_data = get_live_portfolio()
        if live_data:
            status.update(live_data)

    # Calculate runtime from log file timestamp
    if log_file:
        try:
            # Get file creation/modification time
            file_mtime = os.path.getmtime(log_file)
            file_ctime = os.path.getctime(log_file)
            start_time = min(file_mtime, file_ctime)
            # Parse first timestamp from log
            if lines:
                first_line = lines[0] if lines else ""
                match = re.search(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', first_line)
                if match:
                    start_dt = datetime.strptime(match.group(1), '%Y-%m-%d %H:%M:%S')
                    runtime_hours = (datetime.now() - start_dt).total_seconds() / 3600
                    status["runtime_hours"] = runtime_hours
        except:
            pass

    # Portfolio summary
    print(f"{Colors.BOLD}PORTFOLIO SUMMARY{Colors.ENDC}")
    print("-" * 40)
    if is_live_mode:
        total_portfolio = status.get('usdc_balance', 0) + status.get('portfolio_value', 0)
        print(f"  USDC Cash:        ${status.get('usdc_balance', 0):.2f}")
        print(f"  Positions Value:  ${status.get('portfolio_value', 0):.2f}")
        print(f"  Position Cost:    ${status.get('total_cost', 0):.2f}")
        print(f"  Unrealized P&L:   {format_pnl(status.get('pnl', 0))} ({format_pnl_percent(status.get('pnl_percent', 0))})")
        print(f"  {Colors.BOLD}Total Portfolio:  ${total_portfolio:.2f}{Colors.ENDC}")
    else:
        print(f"  Initial Balance:  $1500.00")
        print(f"  Portfolio Value:  ${status['portfolio_value']:.2f}")
        print(f"  P&L:              {format_pnl(status['pnl'])} ({format_pnl_percent(status['pnl_percent'])})")
        print(f"  USDC Available:   ${status['usdc_balance']:.2f}")
    print()

    # Trade statistics
    print(f"{Colors.BOLD}TRADE STATISTICS{Colors.ENDC}")
    print("-" * 40)
    print(f"  Trades Detected:  {status['trades_detected']}")
    print(f"  Trades Copied:    {Colors.GREEN}{status['trades_copied']}{Colors.ENDC}")
    print(f"  Trades Skipped:   {Colors.YELLOW}{status['trades_skipped']}{Colors.ENDC}")
    print(f"  Open Positions:   {status['open_positions']}")
    print(f"  Runtime:          {status['runtime_hours']:.2f} hours")
    print()

    # Open positions
    if status.get('positions'):
        print(f"{Colors.BOLD}OPEN POSITIONS{Colors.ENDC}")
        print("-" * 70)
        
        if is_live_mode:
            # Sort by value descending
            sorted_positions = sorted(status['positions'], key=lambda x: x.get('value', 0), reverse=True)
            for pos in sorted_positions[:10]:  # Show top 10
                name = pos.get('name', '')[:35]
                outcome = pos.get('outcome', '')[:10]
                shares = pos.get('shares', 0)
                value = pos.get('value', 0)
                cost = pos.get('cost', 0)
                pos_pnl = value - cost
                pnl_color = Colors.GREEN if pos_pnl >= 0 else Colors.RED
                print(f"  {name} | {outcome}")
                print(f"    {shares:.1f} shares | Value: ${value:.2f} | {pnl_color}P&L: ${pos_pnl:+.2f}{Colors.ENDC}")
        else:
            for pos in status['positions'][-8:]:  # Show last 8
                name = pos['name'][:40]
                shares = pos['shares']
                price = pos['price']
                value = shares * price
                print(f"  {name}")
                print(f"    {shares:.2f} shares @ ${price:.4f} = ${value:.2f}")
        print()

    # Recent activity
    print(f"{Colors.BOLD}RECENT ACTIVITY{Colors.ENDC}")
    print("-" * 70)

    trades = get_recent_trades(lines, 15)

    for trade in trades[-15:]:
        time_str = trade.get('time', '')[-8:]  # Just HH:MM:SS

        if trade['type'] == 'detected':
            market = trade.get('market', '')[:35]
            side = trade.get('side', '')
            amount = trade.get('amount', '')
            if market:
                print(f"{Colors.CYAN}[{time_str}] DETECTED: {side} ${amount} - {market}{Colors.ENDC}")
            else:
                print(f"{Colors.CYAN}[{time_str}] NEW TRADE DETECTED{Colors.ENDC}")
        elif trade['type'] == 'executed':
            print(f"{Colors.GREEN}[{time_str}] EXECUTED: {trade['side']} ${trade['amount']} @ {trade['price']}{Colors.ENDC}")
        elif trade['type'] == 'success':
            print(f"{Colors.GREEN}[{time_str}] {trade['msg']}{Colors.ENDC}")
        elif trade['type'] == 'skipped':
            print(f"{Colors.YELLOW}[{time_str}] SKIPPED: {trade['reason']}{Colors.ENDC}")
        elif trade['type'] == 'filtered':
            print(f"{Colors.YELLOW}[{time_str}] FILTERED: {trade['msg'][:50]}{Colors.ENDC}")
        elif trade['type'] == 'copy':
            print(f"{Colors.GREEN}[{time_str}] COPY: {trade['msg'][:50]}{Colors.ENDC}")
        elif trade['type'] == 'hedge_skip':
            print(f"{Colors.YELLOW}[{time_str}] HEDGE: {trade['msg'][:50]}{Colors.ENDC}")

    print()
    print(f"{Colors.DIM}Press Ctrl+C to exit | Refreshes every 2 seconds{Colors.ENDC}")


def main():
    """Main loop for live monitoring."""
    print("Starting Polymarket Copy Bot Viewer...")
    print("Monitoring for bot activity...")

    refresh_interval = 2.0  # seconds

    try:
        while True:
            display_dashboard()
            time.sleep(refresh_interval)
    except KeyboardInterrupt:
        print("\nViewer stopped.")
        sys.exit(0)


if __name__ == "__main__":
    main()
