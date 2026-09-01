<?php

namespace Tests\Feature;

use App\Models\Scan;
use App\Models\User;
use App\Models\Company;
use App\Models\Code;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Tests\TestCase;
use App\Enums\ScanType;

uses(RefreshDatabase::class);

test('관리자 전체 스캔 조회', function () {
    $admin = User::factory()->create(['type' => 'admin', 'password' => 'password123']);
    $owner = User::factory()->create(['type' => 'owner', 'password' => 'password123']);
    $tester = User::factory()->create(['type' => 'tester', 'password' => 'password123']);
    $company = Company::factory()->create();

    Scan::factory()->create([
        'company_id' => $company->id,
        'owner_id' => $owner->id,
        'tester_id' => $tester->id
    ]);
    Scan::factory()->create([
        'company_id' => $company->id,
        'owner_id' => $owner->id,
        'tester_id' => $tester->id
    ]);

    $login = $this->postJson('/api/auth/login', [
        'tid' => $admin->tid,
        'password' => 'password123',
    ]);
    $token = $login->json('accessToken');
    $response = $this->withHeaders(['Authorization' => 'Bearer ' . $token])->getJson('/api/scans');
    $response->assertStatus(200)->assertJsonCount(2, 'data');
});

test('관리자 외는 본인 스캔만 조회', function () {
    $owner1 = User::factory()->create(['type' => 'owner', 'password' => 'password123']);
    $owner2 = User::factory()->create(['type' => 'owner', 'password' => 'password123']);
    $tester1 = User::factory()->create(['type' => 'tester', 'password' => 'password123']);
    $tester2 = User::factory()->create(['type' => 'tester', 'password' => 'password123']);
    $company = Company::factory()->create();

    // 오너별 스캔 생성
    Scan::factory()->create([
        'company_id' => $company->id,
        'owner_id' => $owner1->id,
        'tester_id' => $tester1->id
    ]);
    Scan::factory()->create([
        'company_id' => $company->id,
        'owner_id' => $owner2->id,
        'tester_id' => $tester2->id
    ]);

    // 오너1 로그인 후 본인 것만 조회
    $login = $this->postJson('/api/auth/login', [
        'tid' => $owner1->tid,
        'password' => 'password123',
    ]);
    $token = $login->json('accessToken');
    $response = $this->withHeaders(['Authorization' => 'Bearer ' . $token])->getJson('/api/scans');
    $response->assertStatus(200)
        ->assertJsonCount(1, 'data')
        ->assertJsonPath('data.0.ownerId', $owner1->id)
        ->assertJsonMissing(['ownerId' => $owner2->id]);

    // 테스터1 로그인 후 본인 것만 조회
    $login = $this->postJson('/api/auth/login', [
        'tid' => $tester1->tid,
        'password' => 'password123',
    ]);
    $token = $login->json('accessToken');
    $response = $this->withHeaders(['Authorization' => 'Bearer ' . $token])->getJson('/api/scans');
    $response->assertStatus(200)
        ->assertJsonCount(1, 'data')
        ->assertJsonPath('data.0.testerId', $tester1->id)
        ->assertJsonMissing(['testerId' => $tester2->id]);
});

test('타입별 스캔 필터링', function () {
    $admin = User::factory()->create(['type' => 'admin', 'password' => 'password123']);
    $company = Company::factory()->create();

    Scan::factory()->count(5)->create([
        'type' => 'ev',
        'company_id' => $company->id,
        'owner_id' => $admin->id,
        'tester_id' => $admin->id
    ]);
    Scan::factory()->count(5)->create([
        'type' => 'ice',
        'company_id' => $company->id,
        'owner_id' => $admin->id,
        'tester_id' => $admin->id
    ]);

    $login = $this->postJson('/api/auth/login', [
        'tid' => $admin->tid,
        'password' => 'password123',
    ]);
    $token = $login->json('accessToken');
    $response = $this->withHeaders(['Authorization' => 'Bearer ' . $token])->getJson('/api/scans?search=type:ev');
    $response->assertStatus(200)
        ->assertJsonCount(5, 'data')
        ->assertJsonPath('data.0.type', 'ev');
});

test('차량번호로 스캔 필터링', function () {
    $admin = User::factory()->create(['type' => 'admin', 'password' => 'password123']);
    $company = Company::factory()->create();

    Scan::factory()->create([
        'car_no' => '12가3456',
        'company_id' => $company->id,
        'owner_id' => $admin->id,
        'tester_id' => $admin->id
    ]);
    $result = Scan::factory()->create([
        'car_no' => '98나7654',
        'company_id' => $company->id,
        'owner_id' => $admin->id,
        'tester_id' => $admin->id
    ]);

    // 데이터베이스에 정상적으로 저장되었는지 확인
    $this->assertDatabaseHas('scans', [
        'car_no' => '12가3456',
        'company_id' => $company->id,
        'owner_id' => $admin->id,
        'tester_id' => $admin->id
    ]);

    $this->assertDatabaseHas('scans', [
        'car_no' => '98나7654',
        'company_id' => $company->id,
        'owner_id' => $admin->id,
        'tester_id' => $admin->id
    ]);

    // 로그인
    $login = $this->postJson('/api/auth/login', [
        'tid' => $admin->tid,
        'password' => 'password123',
    ]);
    $token = $login->json('accessToken');
    $response = $this->withHeaders(['Authorization' => 'Bearer ' . $token])->getJson('/api/scans?search=carNo:like:12가');

    $response->assertStatus(200)
        ->assertJsonCount(1, 'data')
        ->assertJsonPath('data.0.carNo', '12가3456');
});

test('관계 포함 조회', function () {
    $admin = User::factory()->create(['type' => 'admin', 'password' => 'password123']);
    $company = Company::factory()->create();

    $scan = Scan::factory()->create([
        'company_id' => $company->id,
        'owner_id' => $admin->id,
        'tester_id' => $admin->id
    ]);
    // scanCodes 데이터 생성
    $code = Code::factory()->create();
    $scan->scanCodes()->create([
        'code_id' => $code->id,
        'type' => ScanType::cases()[0]->value
    ]);

    $login = $this->postJson('/api/auth/login', [
        'tid' => $admin->tid,
        'password' => 'password123',
    ]);
    $token = $login->json('accessToken');
    $response = $this->withHeaders(['Authorization' => 'Bearer ' . $token])->getJson('/api/scans?with=owner,tester,company,scanCodes');

    $response->assertStatus(200)
        ->assertJsonStructure([
            'data' => [[
                'owner',
                'tester',
                'company',
                'scanCodes'
            ]]
        ]);
});

test('커스텀 쿼리(페이지 제한)로 조회', function () {
    $admin = User::factory()->create(['type' => 'admin', 'password' => 'password123']);
    $company = Company::factory()->create();

    Scan::factory()->count(5)->create([
        'company_id' => $company->id,
        'owner_id' => $admin->id,
        'tester_id' => $admin->id
    ]);

    $login = $this->postJson('/api/auth/login', [
        'tid' => $admin->tid,
        'password' => 'password123',
    ]);
    $token = $login->json('accessToken');
    $response = $this->withHeaders(['Authorization' => 'Bearer ' . $token])->getJson('/api/scans?per_page=3');
    $response->assertStatus(200)
        ->assertJsonCount(3, 'data');
});

test('다중 조건 검색', function () {
    $admin = User::factory()->create(['type' => 'admin', 'password' => 'password123']);
    $company = Company::factory()->create();

    Scan::factory()->create([
        'type' => 'ev',
        'car_no' => '12가3456',
        'company_id' => $company->id,
        'owner_id' => $admin->id,
        'tester_id' => $admin->id
    ]);
    Scan::factory()->create([
        'type' => 'ev',
        'car_no' => '98나7654',
        'company_id' => $company->id,
        'owner_id' => $admin->id,
        'tester_id' => $admin->id
    ]);
    Scan::factory()->create([
        'type' => 'ice',
        'car_no' => '12가3456',
        'company_id' => $company->id,
        'owner_id' => $admin->id,
        'tester_id' => $admin->id
    ]);

    $login = $this->postJson('/api/auth/login', [
        'tid' => $admin->tid,
        'password' => 'password123',
    ]);
    $token = $login->json('accessToken');
    $response = $this->withHeaders(['Authorization' => 'Bearer ' . $token])->getJson('/api/scans?search=type:ev||carNo:like:12가');

    $response->assertStatus(200)
        ->assertJsonCount(1, 'data')
        ->assertJsonPath('data.0.type', 'ev')
        ->assertJsonPath('data.0.carNo', '12가3456');
});

test('스캔 생성 성공', function () {
    $admin = User::factory()->create(['type' => 'admin', 'password' => 'password123']);
    $owner = User::factory()->create(['type' => 'owner', 'password' => 'password123']);
    $tester = User::factory()->create(['type' => 'tester', 'password' => 'password123']);
    $company = Company::factory()->create();

    $login = $this->postJson('/api/auth/login', [
        'tid' => $admin->tid,
        'password' => 'password123',
    ]);
    $token = $login->json('accessToken');

    $scanData = Scan::factory()->make([
        'type' => 'ev',
        'ownerId' => $owner->id,
        'testerId' => $tester->id,
        'companyId' => $company->id
    ])->toArray();

    $response = $this->withHeaders(['Authorization' => 'Bearer ' . $token])
        ->postJson('/api/scans', $scanData);

    $response->assertStatus(201)
        ->assertJsonStructure([
            'data' => [
                'id',
                'type',
                'deviceType',
                'deviceUid',
                'ownerId',
                'testerId',
                'companyId',
                'scanVin',
                'carNo',
                'carVin',
                'carModel',
                'carCc',
                'carYear',
                'carFuel',
                'carBatteryCapacity',
                'carDischargeEnergy',
                'carChargeEnergy',
                'raw',
                'createdAt',
                'updatedAt'
            ]
        ]);
});

test('테스터 스캔 생성 시 자동 ID 할당', function () {
    $tester = User::factory()->create(['type' => 'tester', 'password' => 'password123']);
    $company = Company::factory()->create();

    $login = $this->postJson('/api/auth/login', [
        'tid' => $tester->tid,
        'password' => 'password123',
    ]);
    $token = $login->json('accessToken');

    $scanData = Scan::factory()->make([
        'type' => 'ev',
        'companyId' => $company->id
    ])->toArray();

    $response = $this->withHeaders(['Authorization' => 'Bearer ' . $token])
        ->postJson('/api/scans', $scanData);

    $response->assertStatus(201)
        ->assertJsonPath('data.testerId', $tester->id)
        ->assertJsonPath('data.ownerId', null);
});

test('오너 스캔 생성 시도 실패', function () {
    $owner = User::factory()->create(['type' => 'owner', 'password' => 'password123']);
    $company = Company::factory()->create();

    $login = $this->postJson('/api/auth/login', [
        'tid' => $owner->tid,
        'password' => 'password123',
    ]);
    $token = $login->json('accessToken');

    $scanData = Scan::factory()->make([
        'type' => 'ev',
        'companyId' => $company->id
    ])->toArray();

    $response = $this->withHeaders(['Authorization' => 'Bearer ' . $token])
        ->postJson('/api/scans', $scanData);
    // dump($response->json());
    $response->assertStatus(403);
});

test('스캔 수정 성공', function () {
    $admin = User::factory()->create(['type' => 'admin', 'password' => 'password123']);
    $owner = User::factory()->create(['type' => 'owner', 'password' => 'password123']);
    $tester = User::factory()->create(['type' => 'tester', 'password' => 'password123']);
    $company = Company::factory()->create();

    $scan = Scan::factory()->create([
        'company_id' => $company->id,
        'owner_id' => $owner->id,
        'tester_id' => $tester->id
    ]);

    $login = $this->postJson('/api/auth/login', [
        'tid' => $admin->tid,
        'password' => 'password123',
    ]);
    $token = $login->json('accessToken');

    $updateData = [
        'car_no' => '98나7654',
        'car_model' => '수정된 모델명'
    ];

    $response = $this->withHeaders(['Authorization' => 'Bearer ' . $token])
        ->putJson("/api/scans/{$scan->id}", $updateData);

    $response->assertStatus(200)
        ->assertJsonPath('data.carNo', '98나7654')
        ->assertJsonPath('data.carModel', '수정된 모델명');
});

test('스캔 수정 실패 - 권한 없음', function () {
    $owner1 = User::factory()->create(['type' => 'owner', 'password' => 'password123']);
    $owner2 = User::factory()->create(['type' => 'owner', 'password' => 'password123']);
    $tester = User::factory()->create(['type' => 'tester', 'password' => 'password123']);
    $company = Company::factory()->create();

    $scan = Scan::factory()->create([
        'company_id' => $company->id,
        'owner_id' => $owner1->id,
        'tester_id' => $tester->id
    ]);

    $login = $this->postJson('/api/auth/login', [
        'tid' => $owner2->tid,
        'password' => 'password123',
    ]);
    $token = $login->json('accessToken');

    $updateData = [
        'carNo' => '98나7654'
    ];

    $response = $this->withHeaders(['Authorization' => 'Bearer ' . $token])
        ->putJson("/api/scans/{$scan->id}", $updateData);
    // dump($response->json());
    $response->assertStatus(404);
});

test('스캔 삭제 성공', function () {
    $admin = User::factory()->create(['type' => 'admin', 'password' => 'password123']);
    $owner = User::factory()->create(['type' => 'owner', 'password' => 'password123']);
    $tester = User::factory()->create(['type' => 'tester', 'password' => 'password123']);
    $company = Company::factory()->create();

    $scan = Scan::factory()->create([
        'company_id' => $company->id,
        'owner_id' => $owner->id,
        'tester_id' => $tester->id
    ]);

    $login = $this->postJson('/api/auth/login', [
        'tid' => $admin->tid,
        'password' => 'password123',
    ]);
    $token = $login->json('accessToken');

    $response = $this->withHeaders(['Authorization' => 'Bearer ' . $token])
        ->deleteJson("/api/scans/{$scan->id}");

    $response->assertStatus(200);
    $this->assertSoftDeleted($scan);
});

test('스캔 삭제 실패 - 권한 없음', function () {
    $owner = User::factory()->create(['type' => 'owner', 'password' => 'password123']);
    $tester1 = User::factory()->create(['type' => 'tester', 'password' => 'password123']);
    $tester2 = User::factory()->create(['type' => 'tester', 'password' => 'password123']);
    $company = Company::factory()->create();

    $scan = Scan::factory()->create([
        'company_id' => $company->id,
        'owner_id' => $owner->id,
        'tester_id' => $tester1->id
    ]);

    // 오너로 로그인 시도
    $ownerLogin = $this->postJson('/api/auth/login', [
        'tid' => $owner->tid,
        'password' => 'password123',
    ]);
    $ownerToken = $ownerLogin->json('accessToken');

    $ownerResponse = $this->withHeaders(['Authorization' => 'Bearer ' . $ownerToken])
        ->deleteJson("/api/scans/{$scan->id}");
    $ownerResponse->assertStatus(403);

    // 다른 테스터로 로그인 시도
    $testerLogin = $this->postJson('/api/auth/login', [
        'tid' => $tester2->tid,
        'password' => 'password123',
    ]);
    $testerToken = $testerLogin->json('accessToken');

    $testerResponse = $this->withHeaders(['Authorization' => 'Bearer ' . $testerToken])
        ->deleteJson("/api/scans/{$scan->id}");
    $testerResponse->assertStatus(404); // 모델에 의해 조회불가
});

test('스캔 상세 조회 성공', function () {
    $admin = User::factory()->create(['type' => 'admin', 'password' => 'password123']);
    $owner = User::factory()->create(['type' => 'owner', 'password' => 'password123']);
    $tester = User::factory()->create(['type' => 'tester', 'password' => 'password123']);
    $company = Company::factory()->create();

    $scan = Scan::factory()->create([
        'company_id' => $company->id,
        'owner_id' => $owner->id,
        'tester_id' => $tester->id
    ]);

    $login = $this->postJson('/api/auth/login', [
        'tid' => $admin->tid,
        'password' => 'password123',
    ]);
    $token = $login->json('accessToken');

    $response = $this->withHeaders(['Authorization' => 'Bearer ' . $token])
        ->getJson("/api/scans/{$scan->id}");
    $response->assertStatus(200)
        ->assertJsonStructure([
            'data' => [
                'id',
                'type',
                'deviceType',
                'deviceUid',
                'ownerId',
                'testerId',
                'companyId',
                'scanVin',
                'carNo',
                'carVin',
                'carModel',
                'createdAt',
                'updatedAt'
            ]
        ]);
});

test('스캔 상세 조회 실패 - 권한 없음', function () {
    $owner1 = User::factory()->create(['type' => 'owner', 'password' => 'password123']);
    $owner2 = User::factory()->create(['type' => 'owner', 'password' => 'password123']);
    $tester = User::factory()->create(['type' => 'tester', 'password' => 'password123']);
    $company = Company::factory()->create();

    $scan = Scan::factory()->create([
        'company_id' => $company->id,
        'owner_id' => $owner1->id,
        'tester_id' => $tester->id
    ]);

    $login = $this->postJson('/api/auth/login', [
        'tid' => $owner2->tid,
        'password' => 'password123',
    ]);
    $token = $login->json('accessToken');

    $response = $this->withHeaders(['Authorization' => 'Bearer ' . $token])
        ->getJson("/api/scans/{$scan->id}");

    $response->assertStatus(404);
});

test('존재하지 않는 스캔 조회', function () {
    $admin = User::factory()->create(['type' => 'admin', 'password' => 'password123']);

    $login = $this->postJson('/api/auth/login', [
        'tid' => $admin->tid,
        'password' => 'password123',
    ]);
    $token = $login->json('accessToken');

    $response = $this->withHeaders(['Authorization' => 'Bearer ' . $token])
        ->getJson('/api/scans/99999');

    $response->assertStatus(404);
});
