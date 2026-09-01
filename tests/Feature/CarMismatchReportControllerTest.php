<?php

use App\Models\CarMismatchReport;
use App\Models\User;
use Illuminate\Foundation\Testing\RefreshDatabase;

uses(RefreshDatabase::class);

test('관리자 전체 불일치 보고서 조회', function () {
    $admin = User::factory()->create(['type' => 'admin', 'password' => 'password123']);
    $user = User::factory()->create(['type' => 'tester', 'password' => 'password123']);

    CarMismatchReport::factory()->create([
        'user_id' => $user->id,
        'car_no' => '12가3456',
        'api_vin' => 'KMHXX00XXXX000000',
        'scan_vin' => 'KMHXX00XXXX000001'
    ]);
    CarMismatchReport::factory()->create([
        'user_id' => $user->id,
        'car_no' => '98나7654',
        'api_vin' => 'KMHXX00XXXX000002',
        'scan_vin' => 'KMHXX00XXXX000003'
    ]);

    $login = $this->postJson('/api/auth/login', [
        'tid' => $admin->tid,
        'password' => 'password123',
    ]);
    $token = $login->json('accessToken');
    $response = $this->withHeaders(['Authorization' => 'Bearer ' . $token])->getJson('/api/carMismatchReports');
    $response->assertStatus(200)
        ->assertJsonCount(2, 'data')
        ->assertJsonStructure([
            'data' => [
                '*' => [
                    'id',
                    'userId',
                    'carNo',
                    'apiVin',
                    'scanVin',
                    'createdAt',
                    'updatedAt'
                ]
            ]
        ]);
});

test('차량번호로 불일치 보고서 필터링', function () {
    $admin = User::factory()->create(['type' => 'admin', 'password' => 'password123']);
    $user = User::factory()->create(['type' => 'tester', 'password' => 'password123']);

    CarMismatchReport::factory()->create([
        'car_no' => '12가3456',
        'user_id' => $user->id,
        'api_vin' => 'KMHXX00XXXX000000',
        'scan_vin' => 'KMHXX00XXXX000001'
    ]);
    CarMismatchReport::factory()->create([
        'car_no' => '98나7654',
        'user_id' => $user->id,
        'api_vin' => 'KMHXX00XXXX000002',
        'scan_vin' => 'KMHXX00XXXX000003'
    ]);

    // 데이터베이스에 정상적으로 저장되었는지 확인
    $this->assertDatabaseHas('car_mismatch_reports', [
        'car_no' => '12가3456',
        'user_id' => $user->id,
        'api_vin' => 'KMHXX00XXXX000000',
        'scan_vin' => 'KMHXX00XXXX000001'
    ]);

    $this->assertDatabaseHas('car_mismatch_reports', [
        'car_no' => '98나7654',
        'user_id' => $user->id,
        'api_vin' => 'KMHXX00XXXX000002',
        'scan_vin' => 'KMHXX00XXXX000003'
    ]);

    // 로그인
    $login = $this->postJson('/api/auth/login', [
        'tid' => $admin->tid,
        'password' => 'password123',
    ]);
    $token = $login->json('accessToken');
    $response = $this->withHeaders(['Authorization' => 'Bearer ' . $token])->getJson('/api/carMismatchReports?search=carNo:like:12가');

    $response->assertStatus(200)
        ->assertJsonCount(1, 'data')
        ->assertJsonPath('data.0.carNo', '12가3456')
        ->assertJsonPath('data.0.apiVin', 'KMHXX00XXXX000000')
        ->assertJsonPath('data.0.scanVin', 'KMHXX00XXXX000001');
});

test('불일치 보고서 생성 성공', function () {
    $user = User::factory()->create(['type' => 'user', 'password' => 'password123']);

    $login = $this->postJson('/api/auth/login', [
        'tid' => $user->tid,
        'password' => 'password123',
    ]);
    $token = $login->json('accessToken');

    $reportData = [
        'car_no' => '12가3456',
        'api_vin' => 'KMHXX00XXXX000000',
        'scan_vin' => 'KMHXX00XXXX000001'
    ];

    $response = $this->withHeaders(['Authorization' => 'Bearer ' . $token])
        ->postJson('/api/carMismatchReports', $reportData);

    // dump($response->json());
    $response->assertStatus(201)
        ->assertJsonStructure([
            'data' => [
                'id',
                'userId',
                'carNo',
                'apiVin',
                'scanVin',
                'createdAt',
                'updatedAt'
            ]
        ])
        ->assertJson([
            'data' => [
                'userId' => $user->id,
                'carNo' => $reportData['car_no'],
                'apiVin' => $reportData['api_vin'],
                'scanVin' => $reportData['scan_vin']
            ]
        ]);

    $this->assertDatabaseHas('car_mismatch_reports', [
        'user_id' => $user->id,
        'car_no' => $reportData['car_no'],
        'api_vin' => $reportData['api_vin'],
        'scan_vin' => $reportData['scan_vin']
    ]);
});

test('불일치 보고서 상세 조회 성공', function () {
    $admin = User::factory()->create(['type' => 'admin', 'password' => 'password123']);
    $user = User::factory()->create(['type' => 'tester', 'password' => 'password123']);

    $report = CarMismatchReport::factory()->create([
        'user_id' => $user->id,
        'car_no' => '12가3456',
        'api_vin' => 'KMHXX00XXXX000000',
        'scan_vin' => 'KMHXX00XXXX000001'
    ]);

    $login = $this->postJson('/api/auth/login', [
        'tid' => $admin->tid,
        'password' => 'password123',
    ]);
    $token = $login->json('accessToken');

    $response = $this->withHeaders(['Authorization' => 'Bearer ' . $token])
        ->getJson("/api/carMismatchReports/{$report->id}");
    $response->assertStatus(200)
        ->assertJsonStructure([
            'data' => [
                'id',
                'userId',
                'carNo',
                'apiVin',
                'scanVin',
                'createdAt',
                'updatedAt'
            ]
        ])
        ->assertJson([
            'data' => [
                'userId' => $user->id,
                'carNo' => '12가3456',
                'apiVin' => 'KMHXX00XXXX000000',
                'scanVin' => 'KMHXX00XXXX000001'
            ]
        ]);
});

test('존재하지 않는 불일치 보고서 조회', function () {
    $admin = User::factory()->create(['type' => 'admin', 'password' => 'password123']);

    $login = $this->postJson('/api/auth/login', [
        'tid' => $admin->tid,
        'password' => 'password123',
    ]);
    $token = $login->json('accessToken');

    $response = $this->withHeaders(['Authorization' => 'Bearer ' . $token])
        ->getJson('/api/carMismatchReports/99999');

    $response->assertStatus(404);
});
