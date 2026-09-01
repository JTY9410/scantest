<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;
use Illuminate\Support\Facades\DB;

return new class extends Migration
{
    public function up(): void
    {
        Schema::create('scans', function (Blueprint $table) {
            $table->id()->comment('아이디');
            $table->enum('type', ['ev', 'ice'])->comment('종류');
            $table->string('device_type')->comment('디바이스 종류');
            $table->string('device_uid')->comment('디바이스 UID');
            $table->foreignId('owner_id')->nullable()->comment('소유자 아이디');
            $table->foreignId('tester_id')->comment('테스터 아이디');
            $table->foreignId('company_id')->nullable()->comment('기업 아이디');
            $table->string('scan_vin')->comment('스캔 차대번호');
            $table->string('car_no')->comment('차량번호');
            $table->string('car_vin')->comment('차대번호');
            $table->string('car_model')->comment('모델명');
            $table->integer('car_cc')->nullable()->comment('배기량');
            $table->integer('car_year')->nullable()->comment('제조년도');
            $table->string('car_fuel')->nullable()->comment('연료타입');
            $table->decimal('car_battery_capacity', 10, 2)->nullable()->comment('배터리 용량 kWh');
            $table->decimal('car_discharge_energy', 10, 2)->nullable()->comment('누적방전전력량');
            $table->decimal('car_charge_energy', 10, 2)->nullable()->comment('누적충전전력량');
            $table->json('raw')->nullable()->comment('스캔로우데이터 JSON');
            $table->timestamps();
            $table->softDeletes();

            // 외래키 제약조건
            $table->foreign('owner_id')->references('id')->on('users')->onDelete('set null');
            $table->foreign('tester_id')->references('id')->on('users')->onDelete('cascade');
            $table->foreign('company_id')->references('id')->on('companies')->onDelete('cascade');
        });
    }

    public function down(): void
    {
        Schema::dropIfExists('scans');
    }
};
