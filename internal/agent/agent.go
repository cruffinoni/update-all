package agent

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
)

func Paths() (service, timer string) {
	home, _ := os.UserHomeDir()
	if runtime.GOOS == "darwin" {
		return filepath.Join(home, "Library/LaunchAgents/com.user.update-all.plist"), ""
	}
	base := filepath.Join(home, ".config/systemd/user")
	return filepath.Join(base, "update-all.service"), filepath.Join(base, "update-all.timer")
}

// Uninstall removes a scheduler installed by an earlier version of update-all.
func Uninstall() error {
	service, timer := Paths()
	if runtime.GOOS == "darwin" {
		if _, err := os.Stat(service); os.IsNotExist(err) {
			fmt.Println("⚠ LaunchAgent plist not found; nothing to uninstall.")
			return nil
		}
		uid, err := exec.Command("id", "-u").Output()
		if err != nil {
			return err
		}
		if err := exec.Command("launchctl", "bootout", "gui/"+strings.TrimSpace(string(uid)), service).Run(); err != nil {
			return fmt.Errorf("launchctl bootout failed: %w", err)
		}
		if err := os.Remove(service); err != nil {
			return err
		}
		fmt.Printf("✓ LaunchAgent uninstalled: %s\n", service)
		return nil
	}
	if _, err := os.Stat(timer); os.IsNotExist(err) {
		fmt.Println("⚠ systemd unit files not found; nothing to uninstall.")
		return nil
	}
	if err := exec.Command("systemctl", "--user", "disable", "--now", "update-all.timer").Run(); err != nil {
		return fmt.Errorf("systemctl disable failed: %w", err)
	}
	_ = os.Remove(timer)
	_ = os.Remove(service)
	_ = exec.Command("systemctl", "--user", "daemon-reload").Run()
	fmt.Printf("✓ systemd timer uninstalled: %s\n", timer)
	return nil
}
