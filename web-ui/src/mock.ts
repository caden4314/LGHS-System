import type { FleetSnapshot } from './types'

export const mockSnapshot: FleetSnapshot = {
  generatedAt: new Date().toISOString(),
  devices: [
    {
      deviceId: 'CS-999', hostname: 'CS-999', health: 'healthy', connectivity: 'online',
      version: '0.6.0', commit: '2428fa0ad4491ec3d13f02580264da9169ca55e8', role: 'student',
      group: 'Validation', tags: ['test-pi'], model: 'Raspberry Pi 5 Model B Rev 1.0', ramMb: 8192,
      cpuPct: 9.2, memPct: 31.4, diskPct: 38.1, tempC: 50.7, wifiDbm: -57,
      rxBps: 28412, txBps: 4212, uptimeSeconds: 22640, lastSeenSeconds: 2.1,
      updateState: null, rebootRequired: false, throttled: false, undervoltage: false,
    },
    {
      deviceId: 'CS-101', hostname: 'CS-101', health: 'warning', connectivity: 'online',
      version: '0.5.4', commit: 'b17b2708f1e80caed32f0ad91fb178bc4f20a74d', role: 'student',
      group: 'Room 101', tags: ['period-1'], model: 'Raspberry Pi 5 Model B Rev 1.0', ramMb: 4096,
      cpuPct: 23.8, memPct: 48.3, diskPct: 72.6, tempC: 61.3, wifiDbm: -78,
      rxBps: 8124, txBps: 2150, uptimeSeconds: 164920, lastSeenSeconds: 4.8,
      updateState: null, rebootRequired: true, throttled: false, undervoltage: false,
    },
    {
      deviceId: 'CS-102', hostname: 'CS-102', health: 'critical', connectivity: 'online',
      version: '0.6.0', commit: '2428fa0ad4491ec3d13f02580264da9169ca55e8', role: 'student',
      group: 'Room 101', tags: ['period-1'], model: 'Raspberry Pi 5 Model B Rev 1.0', ramMb: 4096,
      cpuPct: 82.5, memPct: 73.2, diskPct: 91.8, tempC: 84.1, wifiDbm: -67,
      rxBps: 95123, txBps: 18624, uptimeSeconds: 93210, lastSeenSeconds: 3.2,
      updateState: null, rebootRequired: false, throttled: true, undervoltage: false,
    },
    {
      deviceId: 'CS-103', hostname: 'CS-103', health: 'healthy', connectivity: 'online',
      version: '0.6.0', commit: '2428fa0ad4491ec3d13f02580264da9169ca55e8', role: 'student',
      group: 'Room 101', tags: ['period-2'], model: 'Raspberry Pi 5 Model B Rev 1.0', ramMb: 4096,
      cpuPct: 4.6, memPct: 26.8, diskPct: 34.1, tempC: 47.9, wifiDbm: -54,
      rxBps: 4412, txBps: 1332, uptimeSeconds: 305820, lastSeenSeconds: 1.6,
      updateState: 'validating', rebootRequired: false, throttled: false, undervoltage: false,
    },
    {
      deviceId: 'CS-201', hostname: 'CS-201', health: 'unknown', connectivity: 'stale',
      version: '0.5.4', commit: 'b17b2708f1e80caed32f0ad91fb178bc4f20a74d', role: 'student',
      group: 'Room 201', tags: ['period-4'], model: 'Raspberry Pi 5 Model B Rev 1.0', ramMb: 4096,
      cpuPct: 12.9, memPct: 40.2, diskPct: 42.0, tempC: 52.0, wifiDbm: -82,
      rxBps: 0, txBps: 0, uptimeSeconds: 77450, lastSeenSeconds: 28.4,
      updateState: null, rebootRequired: false, throttled: false, undervoltage: false,
    },
    {
      deviceId: 'CS-202', hostname: 'CS-202', health: 'unknown', connectivity: 'offline',
      version: '0.5.4', commit: 'b17b2708f1e80caed32f0ad91fb178bc4f20a74d', role: 'student',
      group: 'Room 201', tags: ['period-4'], model: 'Raspberry Pi 5 Model B Rev 1.0', ramMb: 4096,
      cpuPct: null, memPct: null, diskPct: null, tempC: null, wifiDbm: null,
      rxBps: null, txBps: null, uptimeSeconds: null, lastSeenSeconds: 684.2,
      updateState: null, rebootRequired: false, throttled: false, undervoltage: false,
    },
  ],
  alerts: [
    { id: 'a1', deviceId: 'CS-102', severity: 'critical', kind: 'temperature', title: 'Temperature is above critical threshold', detail: 'CPU temperature is 84.1 C and throttling has been observed.', observed: '84.1 C', expected: '< 80 C', ageSeconds: 96, acknowledged: false },
    { id: 'a2', deviceId: 'CS-102', severity: 'critical', kind: 'storage', title: 'Root storage pressure', detail: 'Root filesystem is above the warning threshold and close to the critical threshold.', observed: '91.8%', expected: '< 90%', ageSeconds: 1280, acknowledged: false },
    { id: 'a3', deviceId: 'CS-202', severity: 'critical', kind: 'connectivity', title: 'Device is offline', detail: 'No telemetry has been received for more than 60 seconds.', observed: '11m 24s', expected: '< 60s', ageSeconds: 684, acknowledged: false },
    { id: 'a4', deviceId: 'CS-101', severity: 'warning', kind: 'wifi', title: 'Weak Wi-Fi signal', detail: 'The device remains reachable but signal strength is poor.', observed: '-78 dBm', expected: '>= -70 dBm', ageSeconds: 450, acknowledged: false },
    { id: 'a5', deviceId: 'CS-101', severity: 'warning', kind: 'reboot', title: 'Reboot required', detail: 'An OS update requires a reboot to finish applying.', ageSeconds: 8200, acknowledged: false },
  ],
  deployments: [
    { id: 'dep-382d51da', name: 'LGHS 0.6 validation rollout', version: '0.6.0', commit: '2428fa0ad4491ec3d13f02580264da9169ca55e8', state: 'running', completed: 3, total: 5, phase: 2, phases: 3, createdAt: new Date(Date.now() - 31 * 60 * 1000).toISOString() },
  ],
  activity: [
    { id: 'e1', at: new Date(Date.now() - 2 * 60 * 1000).toISOString(), deviceId: 'CS-103', severity: 'info', kind: 'update', message: 'Update entered validation stage', actor: 'fleet-rollout' },
    { id: 'e2', at: new Date(Date.now() - 7 * 60 * 1000).toISOString(), deviceId: 'CS-102', severity: 'critical', kind: 'health', message: 'Temperature crossed critical threshold' },
    { id: 'e3', at: new Date(Date.now() - 14 * 60 * 1000).toISOString(), deviceId: 'CS-202', severity: 'critical', kind: 'connectivity', message: 'Device changed from stale to offline' },
    { id: 'e4', at: new Date(Date.now() - 22 * 60 * 1000).toISOString(), deviceId: 'CS-999', severity: 'info', kind: 'telemetry', message: 'Fleet telemetry verification completed', actor: 'cs_admin' },
  ],
}
