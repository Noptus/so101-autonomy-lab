# Robot model provenance

`so101.urdf` is an unmodified copy of TheRobotStudio/SO-ARM100's
`Simulation/SO101/so101_new_calib.urdf` at commit
`eecbe3e0a9ebb23e25ad7b2759b03884c6660903`.

Source: https://github.com/TheRobotStudio/SO-ARM100/blob/eecbe3e0a9ebb23e25ad7b2759b03884c6660903/Simulation/SO101/so101_new_calib.urdf

SHA-256: `3a65d2d35e68a8d2f0c2cc176d19b884506543c93ba72980145b80abe276022c`

Retrieved through so-paint commit `3209abe06939007fc9a3cf60dfbd55fc82bb6200`
and byte-compared against the original source on 2026-11-21.
Licensed Apache-2.0; see `SO-ARM100-LICENSE`.

Mesh references are retained in the original URDF. STL meshes are not bundled or
loaded: FK/IK use the joint tree, collision checks use explicitly documented capsule
approximations, and the optional MuJoCo backend constructs approximate geometry.
No claim of full-mesh collision or validated dynamics is made.
