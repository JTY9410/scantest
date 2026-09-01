<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration
{
    public function up(): void
    {
        Schema::table('scans', function (Blueprint $table) {
            $table->string('car_maker')->nullable()->after('car_vin')->comment('제조사');
            $table->string('car_submodel')->nullable()->after('car_model')->comment('서브모델');
            $table->longText('bms_data')->nullable()->after('raw')->comment('BMS 데이터(JSON)');
        });
    }

    public function down(): void
    {
        Schema::table('scans', function (Blueprint $table) {
            $table->dropColumn(['car_maker', 'car_submodel', 'bms_data']);
        });
    }
};
